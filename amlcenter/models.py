# -*- coding: utf-8 -*-
"""
Model Definitions for amlcenter

* Many Models use a custom Manager class to limit returned instances of Model

TODO: Find more effective way to do exclude security_marking

Many models use a custom manager to control access to model instances

Ex) Instead of using models.Listing.objects.all() or .filter(...) etc, use:
models.Listing.objects.for_user(user).all() or .filter(...) etc

This way there is a single place to implement this 'tailored view' logic
for model queries

* To Debug select_related
tail -f /var/lib/pgsql/data/pg_log/postgresql-Tue.log -n 0| perl -pe '$_ = "$. $_"'

* inside apply_select_related issues
prefetch_related many-to-many relationships
prefetch_related causes caches issues.
https://github.com/django/django/blob/fea9cb46aacc73cabac883a806ccb7fdc1f979dd/django/db/models/fields/related_descriptors.py
_remove_prefetched_objects does not work property due to self.field.related_query_name() returning wrong value

http://scottlobdell.me/2015/01/sql-database-best-practices-django-orm/
"""
import json
import logging
import os
import uuid
import io
import PIL
from PIL import Image as PilImage

from django.conf import settings
from django.contrib import auth
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.core.validators import MinValueValidator
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.signals import post_delete
from django.db.models.signals import post_save
from django.dispatch import receiver
from rest_framework import serializers

from amlcenter import constants
from amlcenter import utils
from amlcenter.api.listing import elasticsearch_util
from plugins import plugin_manager
system_has_access_control = plugin_manager.system_has_access_control
from aml.storage import media_storage


logger = logging.getLogger('aml-center.' + str(__name__))


def get_user_excluded_orgs(profile_instance):
    """
    Get exclude organizations for private apps

    from amlcenter.models import get_user_excluded_orgs; get_user_excluded_orgs(Profile.objects.get(user__username='wsmith'))
    """
    highest_role = profile_instance.highest_role()
    # having highest_role variable reduce 1949 to 1574 (wsmith)
    if highest_role == 'APPS_MALL_STEWARD':
        exclude_orgs = []
    elif highest_role == 'ORG_STEWARD':
        user_orgs = profile_instance.stewarded_organizations.all()
        # Commenting this out reduce DB 3811 to 3623 for /api/listing
        # user_orgs = [i.title for i in user_orgs]
        exclude_orgs = Agency.objects.exclude(pk__in=user_orgs)
    else:
        user_orgs = profile_instance.organizations.all()
        exclude_orgs = Agency.objects.exclude(pk__in=user_orgs)

    return exclude_orgs


class ImageType(models.Model):
    """
    Image types (as in Small Screenshot, not png)

    This data should be rather static, but is convenient to place in the DB

    listing_small_icon: 16x16
    listing_large_icon: 32x32
    listing_banner_icon: 220x137
    listing_large_banner_icon: 600x376
    listing_small_screenshot: 600x376
    listing_large_screenshot: 960x600
    """
    SMALL_ICON = 'small_icon'
    LARGE_ICON = 'large_icon'
    BANNER_ICON = 'banner_icon'
    LARGE_BANNER_ICON = 'large_banner_icon'
    SMALL_SCREENSHOT = 'small_screenshot'
    LARGE_SCREENSHOT = 'large_screenshot'
    PROFILE_AVATAR = 'profile_avatar'
    NAME_CHOICES = (
        (SMALL_ICON, 'small_icon'),
        (LARGE_ICON, 'large_icon'),
        (BANNER_ICON, 'banner_icon'),
        (LARGE_BANNER_ICON, 'large_banner_icon'),
        (SMALL_SCREENSHOT, 'small_screenshot'),
        (LARGE_SCREENSHOT, 'large_screenshot'),
        (PROFILE_AVATAR, 'profile_avatar'),
    )

    name = models.CharField(max_length=64, choices=NAME_CHOICES, unique=True)
    max_size_bytes = models.IntegerField(default=1048576)
    max_width = models.IntegerField(default=2048)
    max_height = models.IntegerField(default=2048)
    min_width = models.IntegerField(default=16)
    min_height = models.IntegerField(default=16)

    def __repr__(self):
        return self.name

    def __str__(self):
        return self.name


@receiver(post_save, sender=ImageType)
def post_save_image_type(sender, instance, created, **kwargs):
    pass


@receiver(post_delete, sender=ImageType)
def post_delete_image_type(sender, instance, **kwargs):
    pass


class AccessControlImageManager(models.Manager):
    """
    Custom manager to control access to Images
    """

    def apply_select_related(self, queryset):
        queryset = queryset.select_related('image_type')
        return queryset

    def get_queryset(self):
        queryset = super(AccessControlImageManager, self).get_queryset()
        queryset = self.apply_select_related(queryset)
        return queryset

    def for_user(self, username):
        """
        This method causes:
        sqlite3.OperationalError: too many SQL variables
        To fix this error, post filtering in memory needs to happen

        Example Code:
            serializer = serializers.ImageSerializer(queryset, many=True, context={'request': request})
            serializer_iterator = recommend_utils.ListIterator(serializer.data)
            pipeline_list = [pipes.ListingDictPostSecurityMarkingCheckPipe(request.user.username)]

            recommended_listings = pipeline.Pipeline(serializer_iterator, pipeline_list).to_list()
        """
        objects = super(AccessControlImageManager, self).get_queryset()

        # filter out listings by user's access level
        images_to_exclude = []
        for i in objects:
            if not system_has_access_control(username, i.security_marking):
                images_to_exclude.append(i.id)
        objects = objects.exclude(id__in=images_to_exclude)

        return objects


class Image(models.Model):
    """
    Image
    Uploaded images are stored using media_storage (MediaFileStorage/MediaS3Storage)

    When creating a new image, use the Image.create_image method, do not
    use the Image.save() directly

    Note that these images are access controlled, and as such cannot simply
    be statically served
    """
    # this is set automatically by the create_image method
    # TODO: we don't use this, but removiing it causes problems (unit tests
    # segfault. keeping it around doesn't hurt anything, and it could be
    # useful later)
    uuid = models.CharField(max_length=36, unique=True)
    security_marking = models.CharField(max_length=1024)
    file_extension = models.CharField(max_length=16, default='png')
    image_type = models.ForeignKey(ImageType, related_name='images')

    objects = AccessControlImageManager()

    def __repr__(self):
        return 'Image({})'.format(self.id)

    def __str__(self):
        return 'Image({})'.format(self.id)

    @staticmethod
    def create_image(pil_img, **kwargs):
        """
        Given an image (PIL format) and some metadata, then
        - Create database entry
        - Write to media_storage

        TODO: raise exception and remove file and database entry
        TODO: check width and height

        Args:
            pil_img: PIL.Image (see https://pillow.readthedocs.org/en/latest/reference/Image.html)
        """
        TEST_MODE = bool(os.getenv('TEST_MODE', False))

        exception = None
        saved_to_db = False

        random_uuid = str(uuid.uuid4())
        security_marking = kwargs.get('security_marking', 'UNCLASSIFIED')
        file_extension = kwargs.get('file_extension', 'png')
        valid_image_types = constants.VALID_IMAGE_TYPES

        if file_extension not in valid_image_types:
            logger.error('Invalid image type: {0!s}'.format(file_extension))
            exception = Exception('Invalid Image Type, Valid Image type: {}'.format(valid_image_types))

        image_type_obj = kwargs.get('image_type_obj')

        if image_type_obj:
            image_type = image_type_obj
        else:
            image_type = kwargs.get('image_type')
            if not image_type:
                logger.error('No image_type provided')
                exception = Exception('Missing Image Type')
            image_type = ImageType.objects.get(name=image_type)

        # create database entry
        image_object = Image(uuid=random_uuid,
                    security_marking=security_marking,
                    file_extension=file_extension,
                    image_type=image_type)
        image_object.save()
        saved_to_db = True
        # write the image to the file system
        # prefix_file_name = pil_img.fp.name.split('/')[-1].split('.')[0].replace('16','').replace('32','').replace('Featured','')  # Used for export script
        prefix_file_name = str(image_object.id)
        file_name = prefix_file_name + '_' + image_type.name + '.' + file_extension
        ext = os.path.splitext(file_name)[1].lower()
        try:
            current_format = PIL.Image.EXTENSION[ext]
        except KeyError:
            exception = ValueError('unknown file extension: {}'.format(ext))

        if image_object.image_type.name == 'small_icon':
            pil_img = pil_img.resize((16, 16), PilImage.ANTIALIAS)
        elif image_object.image_type.name == 'large_icon':
            pil_img = pil_img.resize((32, 32), PilImage.ANTIALIAS)
        elif image_object.image_type.name == 'banner_icon':
            pil_img = pil_img.resize((220, 137), PilImage.ANTIALIAS)

        # TODO Figure out how to increase Performance on pil_img.save(***)
        # With io.BytesIO(): Sample Data Generator took: 16109.5576171875 ms
        # Commenting out io.BytesIO() - Sample Data Generator took: 34608.710693359375 ms

        if TEST_MODE:
            # Ignore saving file for Tests
            pass
        else:
            image_binary = io.BytesIO()
            pil_img.save(image_binary, format=current_format)

            # image_binary.seek(0)
            size_bytes = image_binary.tell()

            # TODO: PIL saved images can be larger than submitted images.
            # To avoid unexpected image save error, make the max_size_bytes
            # larger than we expect
            if size_bytes > (image_type.max_size_bytes * 2):
                logger.error('Image size is {0:d} bytes, which is larger than the max \
                    allowed {1:d} bytes'.format(size_bytes, 2 * image_type.max_size_bytes))
                exception = Exception('Image Size too big')

        if exception:
            if saved_to_db:
                image_object.delete()
            raise exception

        if TEST_MODE:
            # Ignore saving file for Tests
            pass
        else:
            media_storage.save(file_name, image_binary)
        return image_object


@receiver(post_save, sender=Image)
def post_save_image(sender, instance, created, **kwargs):
    pass


@receiver(post_delete, sender=Image)
def post_delete_image(sender, instance, **kwargs):
    pass


class Tag(models.Model):
    """
    Tag name (for a listing)

    TODO: this will work differently than legacy
    """
    name = models.CharField(max_length=30, unique=True)

    def __repr__(self):
        return self.name

    def __str__(self):
        return self.name


@receiver(post_save, sender=Tag)
def post_save_tag(sender, instance, created, **kwargs):
    pass


@receiver(post_delete, sender=Tag)
def post_delete_tag(sender, instance, **kwargs):
    pass


class Agency(models.Model):
    """
    Agency (like of the three letter variety)

    TODO: Auditing for create, update, delete
    """
    title = models.CharField(max_length=255, unique=True)
    icon = models.ForeignKey(Image, related_name='agency', null=True, blank=True)
    short_name = models.CharField(max_length=32, unique=True)

    def __repr__(self):
        return self.title

    def __str__(self):
        return self.title

    class Meta:
        verbose_name_plural = "agencies"


@receiver(post_save, sender=Agency)
def post_save_agency(sender, instance, created, **kwargs):
    cache.delete_pattern('metadata-*')


@receiver(post_delete, sender=Agency)
def post_delete_agency(sender, instance, **kwargs):
    cache.delete_pattern('metadata-*')


class AccessControlApplicationLibraryEntryManager(models.Manager):
    """
    Use a custom manager to control access to Library
    """

    def apply_select_related(self, queryset):
        queryset = queryset.select_related('listing')
        queryset = queryset.select_related('listing__agency')
        queryset = queryset.select_related('listing__listing_type')
        queryset = queryset.select_related('listing__small_icon')
        queryset = queryset.select_related('listing__large_icon')
        queryset = queryset.select_related('listing__banner_icon')
        queryset = queryset.select_related('listing__large_banner_icon')
        queryset = queryset.select_related('listing__required_listings')
        queryset = queryset.select_related('listing__last_activity')
        queryset = queryset.select_related('listing__current_rejection')
        queryset = queryset.select_related('owner')
        queryset = queryset.select_related('owner__user')
        return queryset

    def get_queryset(self):
        queryset = super(AccessControlApplicationLibraryEntryManager, self).get_queryset()
        return self.apply_select_related(queryset)

    def for_user(self, username):
        objects = super(AccessControlApplicationLibraryEntryManager, self).get_queryset()
        profile_instance = Profile.objects.get(user__username=username)
        # filter out private listings
        exclude_orgs = get_user_excluded_orgs(profile_instance)

        objects = objects.filter(owner__user__username=username)
        objects = objects.filter(listing__is_enabled=True)
        objects = objects.filter(listing__is_deleted=False)
        objects = objects.exclude(listing__is_private=True, listing__agency__in=exclude_orgs)
        objects = self.apply_select_related(objects)
        # Filter out listings by user's access level
        ids_to_exclude = []
        for i in objects:
            if not i.listing.security_marking:
                logger.debug('Listing {0!s} has no security_marking'.format(i.listing.title))
            if not system_has_access_control(username, i.listing.security_marking):
                ids_to_exclude.append(i.listing.id)
        objects = objects.exclude(listing__pk__in=ids_to_exclude)
        return objects

    def for_user_organization_minus_security_markings(self, username, filter_for_user=False):
        objects = super(AccessControlApplicationLibraryEntryManager, self).get_queryset()
        profile_instance = Profile.objects.get(user__username=username)
        # filter out private listings
        exclude_orgs = get_user_excluded_orgs(profile_instance)

        objects = objects.exclude(listing__is_private=True,
                                  listing__agency__in=exclude_orgs)

        if filter_for_user:
            objects = objects.filter(owner__user__username=username)
            objects = objects.filter(listing__is_enabled=True)
            objects = objects.filter(listing__is_deleted=False)

        return objects


class ApplicationLibraryEntry(models.Model):
    """
    A Listing that a user (Profile) has in their 'application library'/bookmarks

    TODO: Auditing for create, update, delete
    TODO: folder seems HUD-specific
    TODO: should we allow multiple bookmarks of the same listing (perhaps in different folders)?
    """
    folder = models.CharField(max_length=255, blank=True, null=True)
    owner = models.ForeignKey('Profile', related_name='application_library_entries')
    listing = models.ForeignKey('Listing', related_name='application_library_entries')
    position = models.PositiveIntegerField(default=0)

    objects = AccessControlApplicationLibraryEntryManager()

    def __str__(self):
        return '{0!s}:{1!s}:{2!s}:{3!s}'.format(self.folder, self.owner.user.username, self.listing.title, self.position)

    def __repr__(self):
        return '{0!s}:{1!s}:{2!s}:{3!s}'.format(self.folder, self.owner.user.username, self.listing.title, self.position)

    class Meta:
        verbose_name_plural = "application library entries"


@receiver(post_save, sender=ApplicationLibraryEntry)
def post_save_application_library_entry(sender, instance, created, **kwargs):
    cache.delete_pattern('library_self-*')


@receiver(post_delete, sender=ApplicationLibraryEntry)
def post_delete_application_library_entry(sender, instance, **kwargs):
    cache.delete_pattern('library_self-*')


class BookmarkEntryManager(models.Manager):
    """
    BookmarkEntry Manager
    """

    def apply_select_related(self, queryset):
        queryset = queryset.select_related('listing')
        # queryset = queryset.select_related('listing__agency')
        # queryset = queryset.select_related('listing__listing_type')
        # queryset = queryset.select_related('listing__small_icon')
        # queryset = queryset.select_related('listing__large_icon')
        # queryset = queryset.select_related('listing__banner_icon')
        # queryset = queryset.select_related('listing__large_banner_icon')
        # queryset = queryset.select_related('listing__required_listings')
        # queryset = queryset.select_related('listing__last_activity')
        # queryset = queryset.select_related('listing__current_rejection')
        queryset = queryset.select_related('creator_profile')
        queryset = queryset.select_related('creator_profile__user')
        return queryset

    def get_queryset(self):
        queryset = super(BookmarkEntryManager, self).get_queryset()
        return self.apply_select_related(queryset)

    def for_profile_minus_security_marking(self, profile_instance):
        objects = super(BookmarkEntryManager, self).get_queryset()
        # filter out private listings
        exclude_orgs = get_user_excluded_orgs(profile_instance)

        objects = objects.filter(listing__is_enabled=True)
        objects = objects.filter(listing__is_deleted=False)
        objects = objects.exclude(listing__is_private=True, listing__agency__in=exclude_orgs)
        objects = self.apply_select_related(objects)
        # Filter out listings by user's access level
        # ids_to_exclude = []
        # for i in objects:
        #     if not i.listing.security_marking:
        #         logger.debug('Listing {0!s} has no security_marking'.format(i.listing.title))
        #     if not system_has_access_control(profile_instance.user.username, i.listing.security_marking):
        #         ids_to_exclude.append(i.listing.id)
        # objects = objects.exclude(listing__pk__in=ids_to_exclude)
        return objects


class BookmarkEntry(models.Model):
    bookmark_parent = models.ManyToManyField('BookmarkEntry', db_table='bookmark_parents')
    # A Bookmark can have many parents.   User1Root ->
    title = models.CharField(max_length=255)

    created_date = models.DateTimeField(default=utils.get_now_utc)
    modified_date = models.DateTimeField(default=utils.get_now_utc)

    listing = models.ForeignKey('Listing', related_name='listing_entries', null=True, blank=True)

    is_root = models.BooleanField(default=False)
    is_public = models.BooleanField(default=False)

    creator_profile = models.ForeignKey('Profile')

    FOLDER = 'FOLDER'
    LISTING = 'LISTING'

    TYPE_CHOICES = (
        (FOLDER, 'FOLDER'),
        (LISTING, 'LISTING'),
    )
    type = models.CharField(max_length=255, choices=TYPE_CHOICES, default=FOLDER)

    objects = BookmarkEntryManager()
    manager = models.Manager()

    def __repr__(self):
        return 'BookmarkEntry({}, bookmark_parent:{},title:{},type:{},is_root:{},listing:{})'.format(
            self.id,
            [parent.title for parent in self.bookmark_parent.all()] if self.bookmark_parent else 'None',
            self.title,
            self.type,
            self.is_root,
            self.listing
        )

    def __str__(self):
        return 'BookmarkEntry({}, bookmark_parent:{},title:{},type:{},is_root:{},listing:{})'.format(
            self.id,
            [parent.title for parent in self.bookmark_parent.all()] if self.bookmark_parent else 'None',
            self.title,
            self.type,
            self.is_root,
            self.listing
        )


class BookmarkPermissionManager(models.Manager):
    """
    BookmarkEntry Manager
    """

    def apply_select_related(self, queryset):
        queryset = queryset.select_related('bookmark')
        queryset = queryset.select_related('profile')
        return queryset

    def get_queryset(self):
        queryset = super(BookmarkPermissionManager, self).get_queryset()
        return self.apply_select_related(queryset)


class BookmarkPermission(models.Model):
    bookmark = models.ForeignKey('BookmarkEntry', related_name='bookmark_permission')  # , on_delete=models.CASCADE)
    profile = models.ForeignKey('Profile')

    created_date = models.DateTimeField(default=utils.get_now_utc)
    modified_date = models.DateTimeField(default=utils.get_now_utc)

    OWNER = 'OWNER'
    VIEWER = 'VIEWER'

    USER_TYPE_CHOICES = (
        (OWNER, 'OWNER'),
        (VIEWER, 'VIEWER'),
    )
    user_type = models.CharField(max_length=255, choices=USER_TYPE_CHOICES, default=VIEWER)

    objects = BookmarkPermissionManager()
    manager = models.Manager()

    class Meta:
        # The same profile should not have multiple permission for the same Bookmark
        unique_together = (('bookmark', 'profile'),)

        indexes = [
            # BookmarkPermission.objects.filter(profile=request_profile, bookmark=bookmark_entry)
            models.Index(fields=['bookmark', 'profile']),
        ]

    def __repr__(self):
        return 'BookmarkPermission(user_type:{},bookmark:{},profile:{})'.format(
            self.user_type,
            self.bookmark,
            self.profile,
        )

    def __str__(self):
        return 'BookmarkPermission(user_type:{},bookmark:{},profile:{})'.format(
            self.user_type,
            self.bookmark,
            self.profile,
        )


class Category(models.Model):
    """
    Categories for Listings

    TODO: Auditing for create, update, delete
    """
    title = models.CharField(max_length=50, unique=True)
    description = models.CharField(max_length=500, null=True, blank=True)

    def __repr__(self):
        return self.title

    def __str__(self):
        return self.title

    class Meta:
        verbose_name_plural = "categories"


@receiver(post_save, sender=Category)
def post_save_category(sender, instance, created, **kwargs):
    cache.delete_pattern('metadata-*')


@receiver(post_delete, sender=Category)
def post_delete_category(sender, instance, **kwargs):
    cache.delete_pattern('metadata-*')


class ChangeDetail(models.Model):
    """
    A change made to a field of a Listing

    Every time a Listing is modified, a ChangeDetail is created for each field
    that was modified

    Additional db.relationships:
        * ListingActivity (ManyToMany)
    """
    field_name = models.CharField(max_length=255)
    old_value = models.CharField(max_length=constants.MAX_VALUE_LENGTH,
                                 blank=True, null=True)
    new_value = models.CharField(max_length=constants.MAX_VALUE_LENGTH,
                                 blank=True, null=True)

    def __repr__(self):
        return "id:{0:d} field {1!s} was {2!s} now is {3!s}".format(
            self.id, self.field_name, self.old_value, self.new_value)


class ContactManager(models.Manager):
    """
    Contact Manager
    """

    def apply_select_related(self, queryset):
        queryset = queryset.select_related('contact_type')
        return queryset

    def get_queryset(self):
        queryset = super(ContactManager, self).get_queryset()
        queryset = self.apply_select_related(queryset)
        return queryset


class Contact(models.Model):
    """
    A contact for a Listing

    TODO: Auditing for create, update, delete
    """
    secure_phone = models.CharField(
        max_length=50,
        validators=[
            RegexValidator(
                regex=constants.PHONE_REGEX,
                message='secure_phone must be a valid phone number',
                code='invalid phone number')],
        null=True,
        blank=True
    )
    unsecure_phone = models.CharField(
        max_length=50,
        validators=[
            RegexValidator(
                regex=constants.PHONE_REGEX,
                message='unsecure_phone must be a valid phone number',
                code='invalid phone number')],
        null=True,
        blank=True
    )
    email = models.CharField(
        max_length=100,
        validators=[
            RegexValidator(
                regex=constants.EMAIL_REGEX,
                message='email must be a valid address',
                code='invalid email')]
    )
    name = models.CharField(max_length=100)
    organization = models.CharField(max_length=100, null=True)
    contact_type = models.ForeignKey('ContactType', related_name='contacts')
    objects = ContactManager()

    def clean(self):
        if not self.secure_phone and not self.unsecure_phone:
            raise ValidationError({'secure_phone': 'Both phone numbers cannot be blank'})

    def __repr__(self):
        val = '{0!s}, {1!s}'.format(self.name, self.email)
        val += 'organization {0!s}'.format((
            self.organization if self.organization else ''))
        val += 'secure_phone {0!s}'.format((
            self.secure_phone if self.secure_phone else ''))
        val += 'unsecure_phone {0!s}'.format((
            self.unsecure_phone if self.unsecure_phone else ''))

        return val

    def __str__(self):
        return '{0!s}: {1!s}'.format(self.name, self.email)


class ContactType(models.Model):
    """
    Contact Type
    Examples: TechnicalPOC, GovieGuy, etc

    TODO: Auditing for create, update, delete
    """
    name = models.CharField(max_length=50, unique=True)
    required = models.BooleanField(default=False)

    def __repr__(self):
        return self.name


@receiver(post_save, sender=ContactType)
def post_save_contact_types(sender, instance, created, **kwargs):
    cache.delete_pattern('metadata-*')


@receiver(post_delete, sender=ContactType)
def post_delete_contact_types(sender, instance, **kwargs):
    cache.delete_pattern('metadata-*')


class DocUrlManager(models.Manager):
    """
    DocUrl Manager
    """

    def apply_select_related(self, queryset):
        queryset = queryset.select_related('listing')
        queryset = queryset.select_related('listing__agency')
        queryset = queryset.select_related('listing__listing_type')
        queryset = queryset.select_related('listing__small_icon')
        queryset = queryset.select_related('listing__large_icon')
        queryset = queryset.select_related('listing__banner_icon')
        queryset = queryset.select_related('listing__large_banner_icon')
        queryset = queryset.select_related('listing__required_listings')
        queryset = queryset.select_related('listing__last_activity')
        queryset = queryset.select_related('listing__current_rejection')
        return queryset

    def get_queryset(self):
        queryset = super(DocUrlManager, self).get_queryset()
        return self.apply_select_related(queryset)


class DocUrl(models.Model):
    """
    A documentation link that belongs to a Listing

    TODO: unique_together constraint on name and url
    """
    name = models.CharField(max_length=255)
    url = models.CharField(
        max_length=constants.MAX_URL_SIZE,
        validators=[
            RegexValidator(
                regex=constants.URL_REGEX,
                message='url must be a url',
                code='invalid url')]
    )
    listing = models.ForeignKey('Listing', related_name='doc_urls')

    objects = DocUrlManager()

    def __repr__(self):
        return '{0!s}:{1!s}'.format(self.name, self.url)

    def __str__(self):
        return '{0!s}: {1!s}'.format(self.name, self.url)


class Intent(models.Model):
    """
    An Intent is an abstract description of an operation to be performed

    TODO: Auditing for create, update, delete
    """
    # TODO unique on type
    action = models.CharField(
        max_length=64,
        validators=[
            RegexValidator(
                regex=constants.INTENT_ACTION_REGEX,
                message='action must be a valid action',
                code='invalid action')]
    )
    media_type = models.CharField(
        max_length=129,
        validators=[
            RegexValidator(
                regex=constants.MEDIA_TYPE_REGEX,
                message='type must be a valid media type',
                code='invalid type')]
    )
    label = models.CharField(max_length=255)
    icon = models.ForeignKey(Image, related_name='intent')

    def __repr__(self):
        return '{0!s}/{1!s}'.format(self.type, self.action)

    def __str__(self):
        return self.action


@receiver(post_save, sender=Intent)
def post_save_intents(sender, instance, created, **kwargs):
    cache.delete_pattern('metadata-*')


@receiver(post_delete, sender=Intent)
def post_delete_intents(sender, instance, **kwargs):
    cache.delete_pattern('metadata-*')


class AccessControlReviewManager(models.Manager):
    """
    Use a custom manager to control access to Reviews
    """

    def apply_select_related(self, queryset):
        queryset = queryset.select_related('listing')
        queryset = queryset.select_related('listing__agency')
        queryset = queryset.select_related('listing__listing_type')
        queryset = queryset.select_related('listing__small_icon')
        queryset = queryset.select_related('listing__large_icon')
        queryset = queryset.select_related('listing__banner_icon')
        queryset = queryset.select_related('listing__large_banner_icon')
        queryset = queryset.select_related('listing__required_listings')
        queryset = queryset.select_related('listing__last_activity')
        queryset = queryset.select_related('listing__current_rejection')

        queryset = queryset.select_related('author')
        queryset = queryset.select_related('author__user')

        queryset = queryset.select_related('review_parent')

        return queryset

    def get_queryset(self):
        queryset = super(AccessControlReviewManager, self).get_queryset()
        return self.apply_select_related(queryset)

    def for_user(self, username):
        # get all reviews
        all_reviews = super(AccessControlReviewManager, self).get_queryset()
        # get all listings for this user
        listings = Listing.objects.for_user(username)

        # filter out reviews for listings this user cannot see
        filtered_reviews = all_reviews.filter(listing__in=listings)

        return filtered_reviews


class Review(models.Model):
    """
    A Review made on a Listing
    """
    review_parent = models.ForeignKey('Review', null=True, blank=True)

    text = models.CharField(max_length=constants.MAX_VALUE_LENGTH, blank=True, null=True)
    rate = models.IntegerField(
        validators=[MinValueValidator(1),
                    MaxValueValidator(5)]
    )
    listing = models.ForeignKey('Listing', related_name='reviews')
    author = models.ForeignKey('Profile', related_name='reviews')

    # TODO: change this back after the database migration
    # edited_date = models.DateTimeField(auto_now=True)
    edited_date = models.DateTimeField(default=utils.get_now_utc)
    created_date = models.DateTimeField(default=utils.get_now_utc)

    objects = AccessControlReviewManager()

    def validate_unique(self, exclude=None):
        queryset = Review.objects.filter(author=self.author, listing=self.listing)
        self_id = self.pk  # If None: it means it is a new review

        if self_id:
            queryset = queryset.exclude(id=self_id)

        if self.review_parent is None:
            queryset = queryset.filter(review_parent__isnull=True, author=self.author)

            if queryset.count() >= 1:
                raise ValidationError('Can not create duplicate review')

        super(Review, self).validate_unique(exclude)

    def save(self, *args, **kwargs):
        self.validate_unique()  # TODO: Figure why when review_parent, pre overwritten validate_unique does not work
        super(Review, self).save(*args, **kwargs)

    def __repr__(self):
        return '[{0!s}] rate: [{1:d}] text:[{2!s}] parent: [{3!s}]'.format(self.author.user.username,
                                          self.rate, self.text, self.review_parent)

    def __str__(self):
        return '[{0!s}] rate: [{1:d}] text:[{2!s}] parent: [{3!s}]'.format(self.author.user.username,
                                          self.rate, self.text, self.review_parent)


class WorkRole(models.Model):
    """
    Work roles for user profiles

    TODO: Auditing for create, update, delete
    """
    name = models.CharField(max_length=30, unique=True)

    def __repr__(self):
        return self.name

    def __str__(self):
        return self.name


class ProfileManager(models.Manager):

    def get_queryset(self):
        queryset = super(ProfileManager, self).get_queryset()
        queryset = queryset.select_related('user')
        return queryset


class Profile(models.Model):
    """
    A User (user's Profile) on AML

    Note that some information (username, email, last_login, date_joined) is
    held in the associated Django User model. In addition, the user's role
    (USER, ORG_STEWARD, or APPS_MALL_STEWARD) is represented by the Group
    associated with the Django User model

    Notes on use of contrib.auth.models.User model:
        * first_name and last_name are not used
        * is_superuser is always set to False
        * is_staff is set to True for Org Stewards and Apps Mall Stewards
        * password is only used in development. On production, client SSL certs
            are used, and so password is set to TODO: TBD

    TODO: Auditing for create, update, delete
        https://github.com/aml-development/aml-backend/issues/61
    """
    display_name = models.CharField(max_length=255)
    bio = models.CharField(max_length=1000, blank=True)
    avatar = models.ForeignKey(Image, related_name='profile_avatar', blank=True, null=True)
    # user's DN from PKI cert
    # ideally this wouldn't be here and in a system using PKI, the user's DN
    # would be the username. DNs can be longer than Django's User.username
    # allows (30 chars max) and can include characters not allowed in
    # User.username
    dn = models.CharField(max_length=1000, unique=True)
    # need to keep track of this as well for making auth calls
    issuer_dn = models.CharField(max_length=1000, null=True, blank=True)
    # datetime when any authorization data becomes
    # TODO: change this back after the migration
    # auth_expires = models.DateTimeField(auto_now_add=True)
    auth_expires = models.DateTimeField(default=utils.get_now_utc)
    organizations = models.ManyToManyField(
        Agency,
        related_name='profiles',
        db_table='agency_profile')
    stewarded_organizations = models.ManyToManyField(
        Agency,
        related_name='stewarded_profiles',
        db_table='stewarded_agency_profile',
        blank=True)

    access_control = models.CharField(max_length=16384)

    # instead of overriding the builtin Django User model used
    # for authentication, we extend it
    # https://docs.djangoproject.com/en/1.8/topics/auth/customizing/#extending-the-existing-user-model
    user = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True)

    # Preferences
    # center_tour_flag: True = Show Tour for center
    center_tour_flag = models.BooleanField(default=True)
    # hud_tour_flag: True = Show Tour for Hud
    hud_tour_flag = models.BooleanField(default=True)
    # webtop_tour_flag: True = Show Tour for Webtop
    webtop_tour_flag = models.BooleanField(default=True)
    # email_notification_flag: True = Send Emails out for notification
    email_notification_flag = models.BooleanField(default=True)
    # listing_notification_flag will disable/enable:
    #   ListingSubmissionNotification, PendingDeletionToStewardNotification, PendingDeletionToOwnerNotification,
    #  ListingPrivateStatusNotification, ListingReviewNotification, ListingNotification, Listing Change,
    #  PendingDeletionApprovedNotification
    listing_notification_flag = models.BooleanField(default=True)
    # subscription_notification_flag  will disable/enable:
    #    TagSubscriptionNotification, CategorySubscriptionNotification
    subscription_notification_flag = models.BooleanField(default=True)
    # leaving_aml_warning_flag: True = Show warning modal when launching an app
    leaving_aml_warning_flag = models.BooleanField(default=True)
    # 508-only-search flag
    only_508_search_flag = models.BooleanField(default=False)

    theme = models.CharField(max_length=255, default='default')

    work_roles = models.ManyToManyField(
        WorkRole,
        related_name='profiles',
        db_table='work_role_profile'
    )

    # TODO: on create, update, or delete, do the same for the related django_user
    objects = ProfileManager()

    def __repr__(self):
        return 'Profile: {0!s}'.format(self.user.username)

    def __str__(self):
        return self.user.username

    @staticmethod
    def create_groups():
        """
        Groups are used as Roles, and as such are relatively static, hence
        their declaration here (NOTE that this must be invoked manually
        after the server has started)
        """
        # create the different Groups (Roles) of users
        auth.models.Group.objects.get_or_create(name='USER')
        auth.models.Group.objects.get_or_create(name='ORG_STEWARD')
        auth.models.Group.objects.get_or_create(name='APPS_MALL_STEWARD')
        auth.models.Group.objects.get_or_create(name='BETA_USER')

    def highest_role(self):
        """
        APPS_MALL_STEWARD > ORG_STEWARD > USER
        """
        groups = self.user.groups.all()
        group_names = [i.name for i in groups]

        if 'APPS_MALL_STEWARD' in group_names:
            return 'APPS_MALL_STEWARD'
        elif 'ORG_STEWARD' in group_names:
            return 'ORG_STEWARD'
        elif 'USER' in group_names:
            return 'USER'
        else:
            # TODO: raise exception?
            logger.error('User {0!s} has invalid Group'.format(self.user.username))
            return ''

    def is_apps_mall_steward(self):
        if self.highest_role() == 'APPS_MALL_STEWARD':
            return True
        return False

    def is_steward(self):
        if self.highest_role() in ['APPS_MALL_STEWARD', 'ORG_STEWARD']:
            return True
        return False

    def is_user(self):
        if self.highest_role() == 'USER':
            return True
        return False

    def is_beta_user(self):
        groups = self.user.groups.all()
        group_names = [i.name for i in groups]
        return 'BETA_USER' in group_names

    @staticmethod
    def create_user(username, **kwargs):
        """
        Create a new User and Profile object

        kwargs:
            password
            email
            display_name
            bio
            access_control
            organizations (['org1_title', 'org2_title'])
            stewarded_organizations (['org1_title', 'org2_title'])
            groups (['group1_name', 'group2_name'])
            dn
            issuer_dn
        """
        # TODO: what to make default password?
        password = kwargs.get('password', 'password')
        email = kwargs.get('email', '')
        # create User object
        # if this user is an ORG_STEWARD or APPS_MALL_STEWARD, give them
        # access to the admin site
        groups = kwargs.get('groups', ['USER'])
        if 'ORG_STEWARD' in groups or 'APPS_MALL_STEWARD' in groups:
            user = auth.models.User.objects.create_superuser(
                username=username, email=email, password=password)
            user.save()
            # logger.warn('creating superuser: %s, password: %s' % (username, password))
        else:
            user = auth.models.User.objects.create_user(
                username=username, email=email, password=password)
            user.save()
            # logger.info('creating user: %s' % username)

        # add user to group(s) (i.e. Roles - USER, ORG_STEWARD,
        # APPS_MALL_STEWARD). If no specific Group is provided, we
        # will default to USER
        for i in groups:
            g = auth.models.Group.objects.get(name=i)
            user.groups.add(g)

        # get additional profile information
        display_name = kwargs.get('display_name', username)
        bio = kwargs.get('password', '')
        ac = kwargs.get('access_control', json.dumps({'clearances': ['U']}))
        access_control = ac
        dn = kwargs.get('dn', username)
        issuer_dn = kwargs.get('issuer_dn')

        # create the profile object and associate it with the User
        p = Profile(display_name=display_name,
                    bio=bio,
                    access_control=access_control,
                    user=user,
                    dn=dn,
                    issuer_dn=issuer_dn
                    )
        p.save()

        # add organizations
        organizations = kwargs.get('organizations', [])
        for i in organizations:
            org = Agency.objects.get(title=i)
            p.organizations.add(org)

        # add stewarded organizations
        organizations = kwargs.get('stewarded_organizations', [])
        for i in organizations:
            org = Agency.objects.get(title=i)
            p.stewarded_organizations.add(org)

        # add work roles
        work_roles = kwargs.get('work_roles', [])
        for i in work_roles:
            work_role = WorkRole.objects.get(name=i)
            p.work_roles.add(work_role)

        return p


class StorefrontCustomizationManager(models.Manager):
    """
    Use a custom manager to control access to storefront customizations
    """

    def apply_select_related(self, queryset):
        queryset = queryset.select_related('profile')
        queryset = queryset.select_related('profile__user')

        return queryset

    def get_queryset(self):
        queryset = super(StorefrontCustomizationManager, self).get_queryset()

        return self.apply_select_related(queryset)

    def for_user(self, username):
        profile_instance = Profile.objects.get(user__username=username)
        objects = self.get_queryset()
        objects = objects.filter(profile=profile_instance)

        return objects


class StorefrontCustomization(models.Model):
    """
    Customization of storefront sections for individual profiles
    """
    FEATURED = 'FEATURED'
    RECOMMENDED = 'RECOMMENDED'
    RECENTLY_ADDED = 'RECENTLY_ADDED'
    MOST_POPULAR = 'MOST_POPULAR'
    FREQUENTLY_VISITED = 'FREQUENTLY_VISITED'
    UPDATES = 'UPDATES'
    MY_LISTINGS = 'MY_LISTINGS'
    SECTION_CHOICES = (
        (FEATURED, FEATURED),
        (RECOMMENDED, RECOMMENDED),
        (RECENTLY_ADDED, RECENTLY_ADDED),
        (MOST_POPULAR, MOST_POPULAR),
        (FREQUENTLY_VISITED, FREQUENTLY_VISITED),
        (UPDATES, UPDATES),
        (MY_LISTINGS, MY_LISTINGS),
    )

    LARGE = 'LARGE'
    SMALL = 'SMALL'
    SIZES = (
        (LARGE, LARGE),
        (SMALL, SMALL)
    )

    profile = models.ForeignKey('Profile', related_name='storefront_customizations')
    section = models.CharField(max_length=50, choices=SECTION_CHOICES)
    position = models.PositiveIntegerField(default=0)
    is_hidden = models.BooleanField(default=False)
    size = models.CharField(max_length=50, choices=SIZES, null=True, blank=True)

    objects = StorefrontCustomizationManager()

    def __str__(self):
        return '{0!s}:{1!s}:{2!s}:{3!s}:{4!s}'.format(self.profile.user.username, self.section, self.position, self.is_hidden, self.size)

    def __repr__(self):
        return '{0!s}:{1!s}:{2!s}:{3!s}:{4!s}'.format(self.profile.user.username, self.section, self.position, self.is_hidden, self.size)

    class Meta:
        unique_together = (("profile", "section"),)


class AccessControlListingManager(models.Manager):
    """
    Use a custom manager to control access to Listings
    """

    def apply_select_related(self, queryset):
        queryset = queryset.select_related('agency')
        queryset = queryset.select_related('agency__icon')
        queryset = queryset.select_related('listing_type')
        queryset = queryset.select_related('agency')
        queryset = queryset.select_related('small_icon')
        queryset = queryset.select_related('small_icon__image_type')
        queryset = queryset.select_related('large_icon')
        queryset = queryset.select_related('large_icon__image_type')
        queryset = queryset.select_related('banner_icon')
        queryset = queryset.select_related('banner_icon__image_type')
        queryset = queryset.select_related('large_banner_icon')
        queryset = queryset.select_related('large_banner_icon__image_type')
        queryset = queryset.select_related('required_listings')
        queryset = queryset.select_related('last_activity')
        queryset = queryset.select_related('current_rejection')
        return queryset

    def get_queryset(self):
        queryset = super(AccessControlListingManager, self).get_queryset()
        return self.apply_select_related(queryset)

    def for_user(self, username):
        objects = super(AccessControlListingManager, self).get_queryset()
        profile_instance = Profile.objects.get(user__username=username)
        # filter out private listings
        exclude_orgs = get_user_excluded_orgs(profile_instance)

        objects = objects.exclude(is_private=True, agency__in=exclude_orgs)
        objects = self.apply_select_related(objects)

        # Filter out listings by user's access level
        ids_to_exclude = []
        for i in objects:
            if not i.security_marking:
                logger.debug('Listing {0!s} has no security_marking'.format(i.title))
            if not system_has_access_control(username, i.security_marking):
                ids_to_exclude.append(i.id)
        objects = objects.exclude(pk__in=ids_to_exclude)

        return objects

    def for_user_organization_minus_security_markings(self, username):
        objects = super(AccessControlListingManager, self).get_queryset()
        profile_instance = Profile.objects.get(user__username=username)
        # filter out private listings
        exclude_orgs = get_user_excluded_orgs(profile_instance)

        objects = objects.exclude(is_private=True, agency__in=exclude_orgs)
        objects = self.apply_select_related(objects)
        return objects


class Listing(models.Model):
    """
    Listing

    To allow users to save Listings in an incompleted state, most of the fields
    in this model are nullable, even though that's not valid for a finalized
    listing
    """
    # Approval Statuses
    # This is the Djangoy mechanism for doing CHOICES fields:
    # https://docs.djangoproject.com/en/1.8/ref/models/fields/#choices
    IN_PROGRESS = 'IN_PROGRESS'
    PENDING = 'PENDING'
    APPROVED_ORG = 'APPROVED_ORG'
    APPROVED = 'APPROVED'
    REJECTED = 'REJECTED'
    DELETED = 'DELETED'
    PENDING_DELETION = 'PENDING_DELETION'
    APPROVAL_STATUS_CHOICES = (
        (IN_PROGRESS, 'IN_PROGRESS'),
        (PENDING, 'PENDING'),
        (APPROVED_ORG, 'APPROVED_ORG'),
        (APPROVED, 'APPROVED'),
        (REJECTED, 'REJECTED'),
        (DELETED, 'DELETED'),
        (PENDING_DELETION, 'PENDING_DELETION')
    )
    # title is not guaranteed to be unique
    title = models.CharField(max_length=255)
    approved_date = models.DateTimeField(null=True, blank=True)
    # TODO: change this back after the migration
    # edited_date = models.DateTimeField(auto_now=True)
    edited_date = models.DateTimeField(default=utils.get_now_utc)
    featured_date = models.DateTimeField(null=True, blank=True)
    agency = models.ForeignKey(Agency, related_name='listings')
    listing_type = models.ForeignKey('ListingType', related_name='listings',
                                     null=True, blank=True)
    description = models.CharField(max_length=8192, null=True, blank=True)
    launch_url = models.CharField(
        max_length=constants.MAX_URL_SIZE,
        validators=[
            RegexValidator(
                regex=constants.URL_REGEX,
                message='launch_url must be a url',
                code='invalid url')
        ], null=True, blank=True
    )
    version_name = models.CharField(max_length=255, null=True, blank=True)
    # NOTE: replacing uuid with this - will need to add to the form
    unique_name = models.CharField(max_length=255, unique=True, null=True, blank=True)
    small_icon = models.ForeignKey(Image, related_name='listing_small_icon', null=True, blank=True)
    large_icon = models.ForeignKey(Image, related_name='listing_large_icon', null=True, blank=True)
    banner_icon = models.ForeignKey(Image, related_name='listing_banner_icon', null=True, blank=True)
    large_banner_icon = models.ForeignKey(Image, related_name='listing_large_banner_icon', null=True, blank=True)

    what_is_new = models.CharField(max_length=255, null=True, blank=True)
    description_short = models.CharField(max_length=150, null=True, blank=True)
    usage_requirements = models.CharField(max_length=1000, null=True, blank=True)
    system_requirements = models.CharField(max_length=1000, null=True, blank=True)
    approval_status = models.CharField(max_length=255, choices=APPROVAL_STATUS_CHOICES, default=IN_PROGRESS)
    is_enabled = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    is_508_compliant = models.BooleanField(default=False)
    # a weighted average (5*total_rate5 + 4*total_rate4 + ...) / total_votes
    avg_rate = models.FloatField(default=0.0)
    total_votes = models.IntegerField(default=0)
    total_rate5 = models.IntegerField(default=0)
    total_rate4 = models.IntegerField(default=0)
    total_rate3 = models.IntegerField(default=0)
    total_rate2 = models.IntegerField(default=0)
    total_rate1 = models.IntegerField(default=0)
    total_reviews = models.IntegerField(default=0)
    total_review_responses = models.IntegerField(default=0)
    feedback_score = models.IntegerField(default=0)
    iframe_compatible = models.BooleanField(default=True)

    contacts = models.ManyToManyField(
        'Contact',
        related_name='listings',
        db_table='contact_listing'
    )

    owners = models.ManyToManyField(
        'Profile',
        related_name='owned_listings',
        db_table='profile_listing'
    )

    categories = models.ManyToManyField(
        'Category',
        related_name='listings',
        db_table='category_listing'
    )

    tags = models.ManyToManyField(
        'Tag',
        related_name='listings',
        db_table='tag_listing'
    )

    required_listings = models.ForeignKey('self', null=True, blank=True)
    # no reverse relationship - use '+'
    last_activity = models.OneToOneField('ListingActivity', related_name='+', null=True, blank=True)
    # no reverse relationship - use '+'
    current_rejection = models.OneToOneField('ListingActivity', related_name='+', null=True, blank=True)

    intents = models.ManyToManyField(
        'Intent',
        related_name='listings',
        db_table='intent_listing'
    )

    security_marking = models.CharField(max_length=1024, null=True, blank=True)

    # private listings can only be viewed by members of the same agency
    is_private = models.BooleanField(default=False)

    objects = AccessControlListingManager()

    def _is_bookmarked(self):
        return False

    def _feedback(self):
        return 0

    is_bookmarked = property(_is_bookmarked)
    feedback = property(_feedback)

    def __repr__(self):
        listing_name = None

        if self.unique_name:
            listing_name = self.unique_name
        elif self.title:
            listing_name = self.title.lower().replace(' ', '_')

        return '({0!s}-{1!s})'.format(listing_name, [owner.user.username for owner in self.owners.all()])

    def __str__(self):
        listing_name = None

        if self.unique_name:
            listing_name = self.unique_name
        elif self.title:
            listing_name = self.title.lower().replace(' ', '_')

        return '({0!s}-{1!s})'.format(listing_name, [owner.user.username for owner in self.owners.all()])

    def save(self, *args, **kwargs):
        """
        TODO: This is not the best place to call elasticsearch update function because it is calling the
             same listing many times
        {'Aliens': 9, 'Albatron Technology': 5, 'Air Mail': 9, 'Alingano Maisu': 9, 'Acoustic Guitar': 9}
        """
        is_new = self.pk
        super(Listing, self).save(*args, **kwargs)
        current_listing_id = self.pk


@receiver(post_save, sender=Listing)
def post_save_listing(sender, instance, created, **kwargs):
    cache.delete_pattern("storefront-*")
    cache.delete_pattern("library_self-*")


@receiver(post_delete, sender=Listing)
def post_delete_listing(sender, instance, **kwargs):
    # TODO: When logic is in place to delete, make sure elasticsearch logic is here
    cache.delete_pattern("storefront-*")
    cache.delete_pattern("library_self-*")


class AccessControlRecommendationsEntryManager(models.Manager):
    """
    Use a custom manager to control access to RecommendationsEntry
    """

    def apply_select_related(self, queryset):
        queryset = queryset.select_related('target_profile')
        queryset = queryset.select_related('target_profile__user')
        return queryset

    def get_queryset(self):
        queryset = super(AccessControlRecommendationsEntryManager, self).get_queryset()
        return self.apply_select_related(queryset)

    def for_user(self, username):
        objects = super(AccessControlRecommendationsEntryManager, self).get_queryset()

        profile_instance = Profile.objects.get(user__username=username)
        # filter out private listings
        exclude_orgs = get_user_excluded_orgs(profile_instance)

        objects = objects.filter(target_profile=profile_instance,
                    listing__is_enabled=True,
                    listing__approval_status=Listing.APPROVED,
                    listing__is_deleted=False)

        objects = objects.exclude(listing__is_private=True,
                                  listing__agency__in=exclude_orgs)

        # Filter out listings by user's access level
        ids_to_exclude = []
        for i in objects:
            if not i.listing.security_marking:
                logger.debug('Listing {0!s} has no security_marking'.format(i.listing.title))
            if not system_has_access_control(username, i.listing.security_marking):
                ids_to_exclude.append(i.listing.id)
        objects = objects.exclude(listing__pk__in=ids_to_exclude)
        return objects

    def for_user_organization_minus_security_markings(self, username):
        objects = super(AccessControlRecommendationsEntryManager, self).get_queryset()

        profile_instance = Profile.objects.get(user__username=username)
        # filter out private listings
        exclude_orgs = get_user_excluded_orgs(profile_instance)

        objects = objects.filter(target_profile=user,
                    listing__is_enabled=True,
                    listing__approval_status=Listing.APPROVED,
                    listing__is_deleted=False)

        objects = objects.exclude(listing__is_private=True, listing__agency__in=exclude_orgs)
        return objects


class RecommendationsEntry(models.Model):
    """
    Recommendations Entry
    """
    target_profile = models.ForeignKey('Profile', related_name='recommendations_profile')
    recommendation_data = models.BinaryField(default=None)

    objects = AccessControlRecommendationsEntryManager()

    def __str__(self):
        return '{0!s}:RecommendationsEntry'.format(self.target_profile)

    def __repr__(self):
        return '{0!s}:RecommendationsEntry'.format(self.target_profile)

    class Meta:
        verbose_name_plural = "recommendations entries"


class AccessControlRecommendationFeedbackManager(models.Manager):
    """
    Use a custom manager to control access to RecommendationsEntry
    """

    def apply_select_related(self, queryset):
        queryset = queryset.select_related('target_profile')
        queryset = queryset.select_related('target_listing')
        return queryset

    def get_queryset(self):
        queryset = super(AccessControlRecommendationFeedbackManager, self).get_queryset()
        return self.apply_select_related(queryset)

    def for_user(self, username):
        objects = super(AccessControlRecommendationFeedbackManager, self).get_queryset()

        profile_instance = Profile.objects.get(user__username=username)
        # filter out private listings
        exclude_orgs = get_user_excluded_orgs(profile_instance)

        objects = objects.filter(target_profile=profile_instance,
                    target_listing__is_enabled=True,
                    target_listing__approval_status=Listing.APPROVED,
                    target_listing__is_deleted=False)

        objects = objects.exclude(target_listing__is_private=True,
                                  target_listing__agency__in=exclude_orgs)

        # Filter out listings by user's access level
        ids_to_exclude = []
        for recommend_feedback_obj in objects:
            if not recommend_feedback_obj.target_listing.security_marking:
                logger.debug('Listing {0!s} has no security_marking'.format(recommend_feedback_obj.target_listing.title))
            if not system_has_access_control(username, recommend_feedback_obj.target_listing.security_marking):
                ids_to_exclude.append(recommend_feedback_obj.target_listing.id)
        objects = objects.exclude(target_listing__pk__in=ids_to_exclude)
        return objects

    def for_user_organization_minus_security_markings(self, username):
        objects = super(AccessControlRecommendationFeedbackManager, self).get_queryset()

        profile_instance = Profile.objects.get(user__username=username)
        # filter out private listings
        exclude_orgs = get_user_excluded_orgs(profile_instance)

        objects = objects.filter(target_profile=profile_instance,
                    target_listing__is_enabled=True,
                    target_listing__approval_status=Listing.APPROVED,
                    target_listing__is_deleted=False)

        objects = objects.exclude(target_listing_is_private=True,
                                  target_listing__agency__in=exclude_orgs)
        return objects


class RecommendationFeedback(models.Model):
    """
    Recommendations Feedback
    """
    target_profile = models.ForeignKey('Profile', related_name='recommendation_feedback_profile')
    target_listing = models.ForeignKey('Listing', related_name='recommendation_feedback_listing')
    feedback = models.IntegerField(default=0)

    objects = AccessControlRecommendationFeedbackManager()

    def __str__(self):
        return '{0!s}:RecommendationFeedback({1!s},, {2!s})'.format(self.target_profile, self.feedback, self.target_listing)

    def __repr__(self):
        return '{0!s}:RecommendationFeedback({1!s}, {2!s})'.format(self.target_profile, self.feedback, self.target_listing)

    class Meta:
        verbose_name_plural = "recommendation feedback"


class AccessControlListingActivityManager(models.Manager):
    """
    Use a custom manager to control access to ListingActivities
    """

    def apply_select_related(self, queryset):
        queryset = queryset.select_related('author')
        queryset = queryset.select_related('listing')
        return queryset

    def get_queryset(self):
        queryset = super(AccessControlListingActivityManager, self).get_queryset()
        return self.apply_select_related(queryset)

    def for_user(self, username):
        all_activities = super(AccessControlListingActivityManager, self).get_queryset()
        listings = Listing.objects.for_user(username).all()
        # filter out listing_activities for listings this user cannot see
        filtered_listing_activities = all_activities.filter(listing__in=listings)
        return filtered_listing_activities


class ListingActivity(models.Model):
    """
    Listing Activity
    """
    # Actions
    # listing is initially created
    CREATED = 'CREATED'
    # field of a listing is modified - has a corresponding ChangeDetail entry
    MODIFIED = 'MODIFIED'
    # listing is submitted for approval by org steward and apps mall steward
    SUBMITTED = 'SUBMITTED'
    # listing is approved by an org steward
    APPROVED_ORG = 'APPROVED_ORG'
    # listing is approved by apps mall steward (upon previous org steward
    # approval) - it is now visible to users
    APPROVED = 'APPROVED'
    # listing is rejected for approval by org steward or apps mall steward
    REJECTED = 'REJECTED'
    # listing is enabled (visible to users)
    ENABLED = 'ENABLED'
    # listing is disabled (hidden from users)
    DISABLED = 'DISABLED'
    # listing is deleted (hidden from users)
    DELETED = 'DELETED'
    # a review for a listing has been modified
    REVIEW_EDITED = 'REVIEW_EDITED'
    # a review for a listing has been deleted
    REVIEW_DELETED = 'REVIEW_DELETED'
    PENDING_DELETION = 'PENDING_DELETION'
    REVIEWED = 'REVIEWED'

    ACTION_CHOICES = (
        (CREATED, 'CREATED'),
        (MODIFIED, 'MODIFIED'),
        (SUBMITTED, 'SUBMITTED'),
        (APPROVED_ORG, 'APPROVED_ORG'),
        (APPROVED, 'APPROVED'),
        (REJECTED, 'REJECTED'),
        (ENABLED, 'ENABLED'),
        (DISABLED, 'DISABLED'),
        (DELETED, 'DELETED'),
        (REVIEWED, 'REVIEWED'),
        (REVIEW_EDITED, 'REVIEW_EDITED'),
        (REVIEW_DELETED, 'REVIEW_DELETED'),
        (PENDING_DELETION, 'PENDING_DELETION')
    )

    action = models.CharField(max_length=128, choices=ACTION_CHOICES)
    # TODO: change this back after the migration
    # activity_date = models.DateTimeField(auto_now=True)
    activity_date = models.DateTimeField(default=utils.get_now_utc)
    # an optional description of the activity (required if the action is REJECTED)
    description = models.CharField(max_length=2000, blank=True, null=True)
    author = models.ForeignKey('Profile', related_name='listing_activities')
    listing = models.ForeignKey('Listing', related_name='listing_activities')
    change_details = models.ManyToManyField(
        'ChangeDetail',
        related_name='listing_activity',
        db_table='listing_activity_change_detail'
    )

    # use a custom Manager class to limit returned activities
    objects = AccessControlListingActivityManager()

    def __repr__(self):
        return '{0!s} {1!s} {2!s} at {3!s}'.format(self.author.user.username, self.action,
                                   self.listing.title, self.activity_date)

    def __str__(self):
        return '{0!s} {1!s} {2!s} at {3!s}'.format(self.author.user.username, self.action,
                                   self.listing.title, self.activity_date)

    class Meta:
        verbose_name_plural = "listing activities"


class AccessControlListingVisitCountManager(models.Manager):
    """
    Use a custom manager to control access to ListingVisitCounts
    """

    def apply_select_related(self, queryset):
        queryset = queryset.select_related('profile')
        queryset = queryset.select_related('listing')
        return queryset

    def get_queryset(self):
        queryset = super(AccessControlListingVisitCountManager, self).get_queryset()
        return self.apply_select_related(queryset)

    def for_user(self, username):
        all_visit_counts = super(AccessControlListingVisitCountManager, self).get_queryset()
        listings = Listing.objects.for_user(username).all()
        filtered_visit_counts = all_visit_counts.filter(listing__in=listings)
        return filtered_visit_counts


class ListingVisitCount(models.Model):
    """
    Listing Visit Count
    """
    profile = models.ForeignKey('Profile', related_name='listing_visit_counts')
    listing = models.ForeignKey('Listing', related_name='listing_visit_counts')
    count = models.PositiveIntegerField(default=0)
    last_visit_date = models.DateTimeField(default=utils.get_now_utc)

    # use a custom Manager class to limit returned counts
    objects = AccessControlListingVisitCountManager()

    def __repr__(self):
        return '{0!s} {1!s}, {2!s} visits, last at {3!s}'.format(self.profile.user.username,
            self.listing.title, self.count, self.last_visit_date)

    def __str__(self):
        return '{0!s} {1!s}, {2!s} visits, last at {3!s}'.format(self.profile.user.username,
            self.listing.title, self.count, self.last_visit_date)


class ScreenshotManager(models.Manager):
    """
    Screenshot Manager
    """

    def apply_select_related(self, queryset):
        queryset = queryset.select_related('small_image')
        queryset = queryset.select_related('large_image')
        queryset = queryset.select_related('listing')
        return queryset

    def get_queryset(self):
        queryset = super(ScreenshotManager, self).get_queryset()
        return self.apply_select_related(queryset)


class Screenshot(models.Model):
    """
    A screenshot for a Listing

    TODO: Auditing for create, update, delete

    Additional db.relationships:
        * listing
    """
    order = models.IntegerField(default=0, null=True)
    small_image = models.ForeignKey(Image, related_name='screenshot_small')
    large_image = models.ForeignKey(Image, related_name='screenshot_large')
    listing = models.ForeignKey('Listing', related_name='screenshots')
    description = models.CharField(max_length=160, null=True, blank=True)
    objects = ScreenshotManager()

    def __repr__(self):
        return '{0!s}: {1!s}, {2!s}'.format(self.listing.title, self.large_image.id, self.small_image.id)

    def __str__(self):
        return '{0!s}: {1!s}, {2!s}'.format(self.listing.title, self.large_image.id, self.small_image.id)


class ListingType(models.Model):
    """
    The type of a Listing
    In NextGen AML, only two listing types are supported: web apps and widgets
    TODO: Auditing for create, update, delete
    """
    title = models.CharField(max_length=50, unique=True)
    description = models.CharField(max_length=255)

    def __repr__(self):
        return self.title

    def __str__(self):
        return self.title


@receiver(post_save, sender=ListingType)
def post_save_listing_types(sender, instance, created, **kwargs):
    cache.delete_pattern('metadata-*')


@receiver(post_delete, sender=ListingType)
def post_delete_listing_types(sender, instance, **kwargs):
    cache.delete_pattern('metadata-*')


class NotificationManager(models.Manager):
    """
    Notification Manager
    """

    def apply_select_related(self, queryset):
        # select_related cut down db calls from 717 to 8
        queryset = queryset.select_related('author')
        queryset = queryset.select_related('author__user')
        queryset = queryset.select_related('listing')
        queryset = queryset.select_related('agency')
        return queryset

    def get_queryset(self):
        queryset = super(NotificationManager, self).get_queryset()
        return self.apply_select_related(queryset)


class Notification(models.Model):
    """
    A notification. Can optionally belong to a specific application

    Notifications that do not have an associated listing are assumed to be
    'system-wide', and thus will be sent to all users
    """
    # TODO: change this back after the database migration
    # created_date = models.DateTimeField(auto_now_add=True)
    created_date = models.DateTimeField(default=utils.get_now_utc)
    message = models.CharField(max_length=4096)
    expires_date = models.DateTimeField()
    author = models.ForeignKey(Profile, related_name='authored_notifications')
    dismissed_by = models.ManyToManyField(
        'Profile',
        related_name='dismissed_notifications',
        db_table='notification_profile'
    )
    listing = models.ForeignKey(Listing, related_name='notifications',
                                null=True, blank=True)
    agency = models.ForeignKey(Agency, related_name='agency_notifications',
                               null=True, blank=True)

    # Peer to Peer Notifications
    # 'peer_org' declaration causes a Segmentation Fault (core dumped) Error in Django Database Library Code
    # django/db/backends/sqlite3/base.py, line 316 in execute

    # peer_org = models.ForeignKey(Profile, related_name='peer_notifications', null=True)
    _peer = models.CharField(max_length=4096, null=True, blank=True, db_column='peer')

    # Notification Type
    SYSTEM = 'system'  # System-wide Notifications
    AGENCY = 'agency'  # Agency-wide Notifications
    AGENCY_BOOKMARK = 'agency_bookmark'  # Agency-wide Bookmark Notifications # Not requirement (erivera 20160621)
    LISTING = 'listing'  # Listing Notifications
    PEER = 'peer'  # Peer to Peer Notifications
    PEER_BOOKMARK = 'peer_bookmark'  # PEER.BOOKMARK - Peer to Peer Bookmark Notifications
    RESTORE_BOOKMARK = 'restore_bookmark'  # RESTORE.BOOKMARK - Self to Self Bookmark Restore
    SUBSCRIPTION = 'subscription'  # SUBSCRIPTION - Tag/Category Subscriptions

    NOTIFICATION_TYPE_CHOICES = (
        (SYSTEM, 'system'),
        (AGENCY, 'agency'),
        (AGENCY_BOOKMARK, 'agency_bookmark'),
        (LISTING, 'listing'),
        (PEER, 'peer'),
        (PEER_BOOKMARK, 'peer_bookmark'),
        (RESTORE_BOOKMARK, 'restore_bookmark'),
        (SUBSCRIPTION, 'subscription'),
    )
    notification_type = models.CharField(default=SYSTEM, max_length=24, choices=NOTIFICATION_TYPE_CHOICES)  # db_index=True)

    # Notification Subtype
    LISTING_NEW = 'listing_new'
    LISTING_REVIEW = 'listing_review'  # When a review is left on a listing
    LISTING_PRIVATE_STATUS = 'listing_private_status'  # When a listing is changed to private
    PENDING_DELETION_TO_OWNER = 'pending_deletion_to_owner'  # When a steward rejects an app deletion request
    PENDING_DELETION_TO_STEWARD = 'pending_deletion_to_steward'  # When an owner submits or cancels an app deletion request
    PENDING_DELETION_APPROVED = 'pending_deletion_approved'  # When a steward approves an app deletion request
    REVIEW_REQUEST = 'review_request'  # When an APP_STEWARD notifies ORG_STEWARDS to review their apps and makes sure they are up to date
    SUBSCRIPTION_CATEGORY = 'subscription_category'  # When there is a new app in a subscribed category
    SUBSCRIPTION_TAG = 'subscription_tag'  # When there is a new app in a subscribed tag

    NOTIFICATION_SUBTYPE_CHOICES = (
        (LISTING_NEW, 'listing_new'),
        (LISTING_REVIEW, 'listing_review'),
        (LISTING_PRIVATE_STATUS, 'listing_private_status'),
        (PENDING_DELETION_TO_OWNER, 'pending_deletion__to_owner'),
        (PENDING_DELETION_TO_STEWARD, 'pending_deletion_to_steward'),
        (PENDING_DELETION_APPROVED, 'pending_deletion_approved'),
        (REVIEW_REQUEST, 'review_request'),
        (SUBSCRIPTION_CATEGORY, 'subscription_category'),
        (SUBSCRIPTION_TAG, 'subscription_tag')
    )
    notification_subtype = models.CharField(default=SYSTEM, max_length=36, choices=NOTIFICATION_SUBTYPE_CHOICES, null=True)  # db_index=True)

    # User Target
    ALL = 'all'  # All users
    STEWARDS = 'stewards'
    APP_STEWARD = 'app_steward'
    ORG_STEWARD = 'org_steward'
    USER = 'user'
    OWNER = 'owner'

    GROUP_TARGET_CHOICES = (
        (ALL, 'all'),
        (STEWARDS, 'stewards'),
        (APP_STEWARD, 'app_steward'),
        (ORG_STEWARD, 'org_steward'),
        (USER, 'user'),
        (OWNER, 'owner'),
    )
    group_target = models.CharField(default=ALL, max_length=24, choices=GROUP_TARGET_CHOICES)  # db_index=True)

    # Depending on notification_type, it could be listing_id/agency_id/profile_user_id/category_id/tag_id
    entity_id = models.IntegerField(default=None, null=True, blank=True, db_index=True)

    objects = NotificationManager()

    @property
    def peer(self):
        if self._peer:
            return json.loads(self._peer)
        else:
            return None

    @peer.setter
    def peer(self, value):
        """
        Setter for peer variable

        {
            'user': {
                'username': str
            },
            '_bookmark_listing_ids': list[int],
            'folder_name': str,
            'deleted_folder': bool
        }

        Args:
            value (dict): dictionary
        """
        if value:
            assert isinstance(value, dict), 'Argument of wrong type is not a dict'

            temp = {}

            if 'user' in value:
                temp_user = {}
                current_user_dict = value['user']
                assert isinstance(current_user_dict, dict), 'Argument of wrong type is not a dict'

                if 'username' in current_user_dict:
                    temp_user['username'] = current_user_dict['username']

                temp['user'] = temp_user

            for entry_key in ['folder_name', '_bookmark_listing_ids']:
                if entry_key in value:
                    temp[entry_key] = value[entry_key]

            if 'deleted_folder' in value:
                temp['deleted_folder'] = True
            self._peer = json.dumps(temp)
        else:
            return None

    def __repr__(self):
        return '{0!s}: {1!s}'.format(self.author.user.username, self.message)

    def __str__(self):
        return '{0!s}: {1!s}'.format(self.author.user.username, self.message)


class NotificationMailBoxManager(models.Manager):
    """
    NotificationMailBox Manager
    """

    def apply_select_related(self, queryset):
        queryset = queryset.select_related('target_profile')
        queryset = queryset.select_related('notification')
        return queryset

    def get_queryset(self):
        queryset = super(NotificationMailBoxManager, self).get_queryset()
        return self.apply_select_related(queryset)


class NotificationMailBox(models.Model):
    """
    Notification MailBox
    Represents all the notifications for all users

    Fields:
        target_profile: Mailbox Profile ID
        notification: notification ForeignKey
        emailed_status: If it has been emailed. then make value true
        read_status: Read Flag
        acknowledged_status: Acknowledged Flag
    """
    target_profile = models.ForeignKey(Profile, related_name='mailbox_profiles')
    notification = models.ForeignKey(Notification, related_name='mailbox_notifications')
    emailed_status = models.BooleanField(default=False)
    read_status = models.BooleanField(default=False)
    acknowledged_status = models.BooleanField(default=False)

    objects = NotificationMailBoxManager()

    def __repr__(self):
        return '{0!s}: {1!s}'.format(self.target_profile.user.username, self.notification.pk)

    def __str__(self):
        return '{0!s}: {1!s}'.format(self.target_profile.user.username, self.notification.pk)


class Subscription(models.Model):
    target_profile = models.ForeignKey(Profile, related_name='subscription_profiles')

    # Entity Type
    CATEGORY = 'category'
    TAG = 'tag'

    ENTITY_TYPE_CHOICES = (
        (CATEGORY, 'category'),
        (TAG, 'tag'),
    )
    entity_type = models.CharField(default=None, max_length=12, choices=ENTITY_TYPE_CHOICES, db_index=True)

    # Depending on entity_type, it could be category_id/agency_id/tag_id
    entity_id = models.IntegerField(default=None, db_index=True)

    def __repr__(self):
        return '{0!s}: {1!s}: {2!s}'.format(self.target_profile.user.username, self.entity_type, self.entity_id)

    def __str__(self):
        return '{0!s}: {1!s}: {2!s}'.format(self.target_profile.user.username, self.entity_type, self.entity_id)
