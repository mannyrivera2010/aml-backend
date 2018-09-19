"""
https://github.com/aml-development/aml-documentation/wiki/Notifications

Notification Type
    SYSTEM = 'system'  # System-wide Notifications
    AGENCY = 'agency'  # Agency-wide Notifications
    AGENCY_BOOKMARK = 'agency_bookmark'  # Agency-wide Bookmark Notifications # Not requirement (erivera 20160621)
    LISTING = 'listing'  # Listing Notifications
    PEER = 'peer'  # Peer to Peer Notifications
    PEER_BOOKMARK = 'peer_bookmark'  # Peer to Peer Bookmark Notifications
    SUBSCRIPTION = 'subscription' # Category and Tag Subscription Notification

Group Target
    ALL = 'all'  # All users
    STEWARDS = 'stewards'
    APP_STEWARD = 'app_steward'
    ORG_STEWARD = 'org_steward'
    USER = 'user'
=====Notification Type=====

                +--> SystemWide
                |
                +--> AgencyWide
                |
                +--> AgencyWideBookmark
                |
Notification +------+--> Listing
                |   |
                |   +--> ListingReview
                |   |
                |   +--> ListingPrivateStatus
                |   |
                |   +--> PendingDeletionToOwner
                |   |
                |   +--> PendingDeletionToSteward
                |   |
                |   +--> PendingDeletionApproved
                |   |
                |   +--> ListingSubmission
                |
                +--> Peer
                |
                +--> PeerBookmark
                |
                +--> CategorySubscription
                |
                +--> TagSubscription

=====Vocab=====
Target: is a Profile that should receive a notification
Target List: A list of Profiles that should receive notifications
Direct notification: The notification is produced by an action that the user does.
In-direct Notification: The notification is produced by the observing a user action.
"""
import datetime
import logging
import pytz

from django.db.models import Q
from django.db import transaction

from amlcenter import errors

from amlcenter.models import Notification
from amlcenter.models import NotificationMailBox
from amlcenter.models import Profile
from amlcenter.models import Agency
from amlcenter.models import Listing
from amlcenter.models import ApplicationLibraryEntry
from amlcenter.models import BookmarkEntry
from amlcenter.models import Subscription

import amlcenter.model_access as generic_model_access
from amlcenter.wsservice.wsclient import web_service_client


logger = logging.getLogger('aml-center.' + str(__name__))


permission_dict = {
    'APPS_MALL_STEWARD': [
        'add_system_notification',
        'change_system_notification',
        'delete_system_notification',

        'add_agency_notification',
        'change_agency_notification',
        'delete_agency_notification',

        'add_listing_notification',
        'change_listing_notification',
        'delete_listing_notification',

        'add_peer_notification',
        'change_peer_notification',
        'delete_peer_notification',

        'add_peer_bookmark_notification',
        'add_restore_bookmark_notification',
        'change_peer_bookmark_notification',
        'delete_peer_bookmark_notification',

        'add_subscription_notification',
        'change_subscription_notification',
        'delete_subscription_notification'
    ],
    'ORG_STEWARD': [
        'add_system_notification',
        'change_system_notification',
        'delete_system_notification',

        'add_agency_notification',
        'change_agency_notification',
        'delete_agency_notification',

        'add_listing_notification',
        'change_listing_notification',
        'delete_listing_notification',

        'add_peer_notification',
        'change_peer_notification',
        'delete_peer_notification',

        'add_peer_bookmark_notification',
        'add_restore_bookmark_notification',
        'change_peer_bookmark_notification',
        'delete_peer_bookmark_notification',

        'add_subscription_notification',
        'change_subscription_notification',
        'delete_subscription_notification'
    ],
    'USER': [
        'add_listing_notification',
        'change_listing_notification',
        'delete_listing_notification',

        'add_peer_notification',
        'change_peer_notification',
        'delete_peer_notification',

        'add_peer_bookmark_notification',
        'add_restore_bookmark_notification',
        'change_peer_bookmark_notification',
        'delete_peer_bookmark_notification',

        'add_subscription_notification',
        'change_subscription_notification',
        'delete_subscription_notification'
        ]
}


def get_owners_for_bookmark_entry(listing):
    """
    Get profile for Bookmark Entry

    Returns:
        List of integers of profile ids
    """
    owner_id_list = (BookmarkEntry.objects
        .filter(
            listing__in=[listing],
            listing__isnull=False,
            listing__approval_status=Listing.APPROVED,
            # listing__is_enabled=True,
            listing__is_deleted=False)
        .values_list('bookmark_parent__bookmark_permission__profile', flat=True)
        .distinct())

    return list(owner_id_list)


def get_owners_for_application_library_entry(listing):
    """
    Get profile for Application Library Entry

    Returns:
        List of integers of profile ids
    """
    owner_id_list = (ApplicationLibraryEntry.objects
        .filter(
            listing__in=[listing],
            listing__isnull=False,
            listing__approval_status=Listing.APPROVED,
            # listing__is_enabled=True,
            listing__is_deleted=False)
        .values_list('owner', flat=True)
        .distinct())
    return list(owner_id_list)


def get_owners_for_bookmark_3_2(listing):
    """
    Get a list of profiles for bookmarks (ApplicationLibraryEntry and BookmarkEntry)
    """
    bookmark_entry_owners = set(get_owners_for_bookmark_entry(listing))
    application_library_entry_owners = set(get_owners_for_application_library_entry(listing))
    return list(bookmark_entry_owners.union(application_library_entry_owners))


# Method is decorated with @transaction.atomic to ensure all logic is executed in a single transaction
@transaction.atomic
def bulk_notifications_saver(notification_instances):
    # Loop over each store and invoke save() on each entry
    for notification_instance in notification_instances:
        notification_instance.save()


def check_notification_permission(profile_instance, action, notification_type):
    """
    Check to see if user has permission

    Args:
        profile_instance(Profile): Profile Instance
        action(string): add/change/delete
        notification_type(string): notification type
    Return:
        True or PermissionDenied Exception
    """
    profile_role = profile_instance.highest_role()
    assert (profile_role in permission_dict), 'Profile group {} not found in permissions'.format(profile_role)

    user_action = '{}_{}_notification'.format(action, notification_type)

    profile_permission_list = permission_dict[profile_role]

    if user_action not in profile_permission_list:
        raise errors.PermissionDenied('Profile does not have [{}] permissions'.format(user_action))

    return True


class NotificationBase(object):
    """
    Process:
        Init NotificationBase Super Class Object
        Set sender_profile and entities list
        Validate sender_profile and entities list
        Do Global Permission Check

        Notify
            Validate expires_date, message
    """

    def set_sender_and_entity(self, sender_profile_username, entity_dict):
        """
        Set Sender Profile, entity object, metadata

        Args:
            sender_profile_username(string): Sender's Profile username (normally the request profile)
            entity(object):
        """
        assert (sender_profile_username is not None), 'Sender Profile Username is necessary'

        self.sender_profile_username = sender_profile_username
        self.sender_profile = generic_model_access.get_profile(sender_profile_username)
        self.entity_dict = entity_dict

    def check_local_permission(self, entity):
        return True

    def permission_check(self):
        """
        Global and Local check
        """
        check_notification_permission(self.sender_profile, 'add', self.get_notification_db_type())
        self.check_local_permission(self.entity_dict)

    def generate_model(self, expires_date, message):
        notification = Notification()
        notification.expires_date = expires_date
        notification.message = message
        notification.author = self.sender_profile
        notification.notification_type = self.get_notification_db_type()
        notification.notification_subtype = self.get_notification_db_subtype()
        notification.entity_id = self.get_entity_id()
        notification.group_target = self.get_group_target()
        return notification

    def get_notification_db_type(self):
        raise RuntimeError('Not Implemented')

    def get_notification_db_subtype(self):
        return None

    def get_entity_id(self):
        return None

    def get_group_target(self):
        return Notification.ALL

    def get_target_list(self):
        raise RuntimeError('Not Implemented')

    def modify_notification_before_save(self, notification_object):
        pass

    def notify(self, expires_date, message):
        assert (expires_date is not None), 'Expires Date is necessary'
        assert (message is not None), 'Message is necessary'
        self.permission_check()

        notification = self.generate_model(expires_date, message)
        self.modify_notification_before_save(notification)

        notification.save()

        target_list = self.get_target_list()

        bulk_notification_list = []

        for target_profile in target_list:
            notificationMailBox = NotificationMailBox()
            notificationMailBox.target_profile = target_profile
            notificationMailBox.notification = notification
            # All the flags default to false
            notificationMailBox.emailed_status = False

            bulk_notification_list.append(notificationMailBox)

            if len(bulk_notification_list) >= 2000:
                bulk_notifications_saver(bulk_notification_list)
                bulk_notification_list = []

        if bulk_notification_list:
            bulk_notifications_saver(bulk_notification_list)
            web_service_client.send_bulk_message(self.sender_profile, bulk_notification_list)

        return notification


class SystemWideNotification(NotificationBase):
    """
    issue: AMLNG-395
    notification_type: System Wide
    description:
        As a user, I want to receive System-Wide Notifications
    target: All Users
    permission constraint: Only APP_MALL_STEWARDs can send notifications
    invoked: Directly
    test_case:
        todo
    """

    def get_notification_db_type(self):
        return Notification.SYSTEM

    def get_notification_db_subtype(self):
        return None

    def get_target_list(self):
        return Profile.objects.all()


class AgencyWideNotification(NotificationBase):
    """
    issue: AMLNG-398
    notification_type: Agency Wide
    description:
        As a user, I want to receive Agency-Wide Notifications
    target: Get all profiles that belongs to an organization and get all stewards for that organization
    permission constraint: Only APP_MALL_STEWARDs, ORG_STEWARDs can send notifications
    invoked: Directly
    test_case:
        todo
    """

    def modify_notification_before_save(self, notification_object):
        notification_object.agency = self.entity_dict['agency']

    def get_notification_db_type(self):
        return Notification.AGENCY

    def get_notification_db_subtype(self):
        return None

    def get_entity_id(self):
        return self.entity_dict['agency'].id

    def get_target_list(self):
        agency = self.entity_dict['agency']
        return Profile.objects.filter(Q(organizations__in=[agency]) |
                                      Q(stewarded_organizations__in=[agency])).all()


class AgencyWideBookmarkNotification(NotificationBase):
    """
    issue: AMLNG-398
    notification_type: AgencyWide Bookmark
    description:
        As a user, I want to receive Agency-Wide Notifications
    target: Get all profiles that belongs to an organization and get all stewards for that organization
    permission constraint: Only APP_MALL_STEWARDs, ORG_STEWARDs can send notifications
    invoked: Directly
    test_case:
        todo
    """

    def modify_notification_before_save(self, notification_object):
        notification_object.agency = self.entity_dict['agency']

    def get_notification_db_type(self):
        return Notification.AGENCY_BOOKMARK

    def get_notification_db_subtype(self):
        return None

    def get_entity_id(self):
        return self.entity_dict['agency'].id

    def get_target_list(self):
        agency = self.entity_dict['agency']
        return Profile.objects.filter(Q(organizations__in=[agency]) |
                                      Q(stewarded_organizations__in=[agency])).all()


class ListingNotification(NotificationBase):
    """
    issue: AMLNG-396
    notification_type: Listing Notifications
    description:
        Send a notification to all the users that bookmark given listing
    target: All users that bookmarked listing
    permission constraint: Only APP_MALL_STEWARDs and ORG_STEWARDs or owners of listing can send notifications
    invoked: Directly
    test_case:
        todo
    """

    def modify_notification_before_save(self, notification_object):
        notification_object.listing = self.entity_dict['listing']

    def get_notification_db_type(self):
        return Notification.LISTING

    def get_notification_db_subtype(self):
        return None

    def get_entity_id(self):
        return self.entity_dict['listing'].id

    def get_target_list(self):
        owner_id_list = get_owners_for_bookmark_3_2(self.entity_dict['listing'])
        profile_list = Profile.objects.filter(id__in=owner_id_list, listing_notification_flag=True).all()
        return profile_list

    def check_local_permission(self, entity):
        if self.sender_profile.highest_role() in ['APPS_MALL_STEWARD', 'ORG_STEWARD']:
            return True

        if self.sender_profile not in self.entity_dict['listing'].owners.all():
            raise errors.PermissionDenied('Cannot create a notification for a listing you do not own')
        else:
            return True
        return False


class ListingUpdateNotification(NotificationBase):

    def modify_notification_before_save(self, notification_object):
        notification_object.listing = self.entity_dict['listing']

    def get_entity_id(self):
        return self.entity_dict['listing'].id

    def get_notification_db_type(self):
        return Notification.LISTING

    def get_notification_db_subtype(self):
        return Notification.LISTING_PRIVATE_STATUS

    def get_target_list(self):
        owner_id_list = get_owners_for_bookmark_3_2(self.entity_dict['listing'])
        return Profile.objects.filter(id__in=owner_id_list, listing_notification_flag=True).all()

    def check_local_permission(self, entity):
        if self.sender_profile.highest_role() in ['APPS_MALL_STEWARD', 'ORG_STEWARD']:
            return True

        if self.sender_profile not in self.entity_dict['listing'].owners.all():
            raise errors.PermissionDenied('Cannot create a notification for a listing you do not own')
        else:
            return True
        return False


class PeerNotification(NotificationBase):
    """
    issue: AMLNG-381
    notification_type: Peer
    description:
        As a user, I want to receive notification when someone send a message to me
    target: User Given Target
    permission constraint: ?
    test_case:
        todo
    """

    def modify_notification_before_save(self, notification_object):
        notification_object.peer = self.entity_dict['peer']

    def get_notification_db_type(self):
        return Notification.PEER

    def get_notification_db_subtype(self):
        return None

    def get_group_target(self):
        return Notification.USER

    def get_target_list(self):
        # entity: 'peer_profile': peer_profile,
        # metadata: 'peer': peer,
        entities_id = [entity.id for entity in [self.entity_dict['peer_profile']]]
        return Profile.objects.filter(id__in=entities_id).all()


class PeerBookmarkNotification(NotificationBase):
    """
    issue: AMLNG-381
    notification_type: PeerBookmark
    description:
        As a user, I want to receive notification when someone shares a folder with me
    target: User Given Target
    permission constraint:  Must be owner of shared folder to send
    test_case:
        Logged on as jones
        Shared a folder with aaronson
        Logged on as aaronson
        RESULTS: aaronson has a new notification added to the notification count.Add folder button is present and adds the shared folder to HuD screen.
    """

    def modify_notification_before_save(self, notification_object):
        notification_object.peer = self.entity_dict['peer']

    def get_notification_db_type(self):
        return Notification.PEER_BOOKMARK

    def get_notification_db_subtype(self):
        return None

    def get_group_target(self):
        return Notification.USER

    def get_target_list(self):
        # entity: 'peer_profile': peer_profile,
        # metadata: 'peer': peer,
        entities_id = [entity.id for entity in [self.entity_dict['peer_profile']]]
        return Profile.objects.filter(id__in=entities_id).all()


class RestoreBookmarkNotification(NotificationBase):
    """
    issue: AMLNG-700
    notification_type: Restore Bookmark Folder
    description:
        As a user, I would like the ability to be able to recover a deleted folder full of bookmarked listings with an undo delete function.
    target: User Given Target
    permission constraint:  Must be owner of folder
    test_case:
        Logged on as jones
        Delete a folder
        Restore folder from Notifications
        RESULTS: Restore folder button is present and readds the folder to HuD screen.
    """

    def modify_notification_before_save(self, notification_object):
        notification_object.peer = self.entity_dict['peer']

    def get_notification_db_type(self):
        return Notification.RESTORE_BOOKMARK

    def get_notification_db_subtype(self):
        return None

    def get_group_target(self):
        return Notification.USER

    def get_target_list(self):
        entities_id = [entity.id for entity in [self.entity_dict['peer_profile']]]
        return Profile.objects.filter(id__in=entities_id).all()


class ListingReviewNotification(NotificationBase):  # Not Verified
    """
    issue: AMLNG-377
    notification_type: Listing Review
    description:
        As an owner or CS, I want to receive notification of user rating and reviews
    target: Users that ___
    invoked: In-directly
    test_case:
        Description - Verify the CS and listing owner receives a notification when the review is added or modified.
        *Pre-req*- Add aaronson as listing owner to Airmail.
        Log on as syme (minipax)
        Deleted, Added and Modified review on Airmail ( minitru)
        Log on as wsmith (minitru-org steward)
        EXPECTED RESULTS - At least two notifications should display for wsmith.
        Log on as aaronson
        EXPECTED RESULTS - At least two notifications should display for aaronson.
    """

    def modify_notification_before_save(self, notification_object):
        notification_object.listing = self.entity_dict['listing']

    def get_notification_db_type(self):
        return Notification.LISTING

    def get_notification_db_subtype(self):
        return Notification.LISTING_REVIEW

    def get_group_target(self):
        return Notification.USER

    def get_entity_id(self):
        return self.entity_dict['listing'].id

    def get_target_list(self):
        current_listing = self.entity_dict['listing']

        target_set = set()

        for owner in current_listing.owners.filter(listing_notification_flag=True).all():
            target_set.add(owner)

        current_listing_agency_id = current_listing.agency.id

        for steward in Profile.objects.filter(stewarded_organizations__in=[current_listing_agency_id], listing_notification_flag=True).all():
            target_set.add(steward)

        return list(target_set)


class ListingOwnerNotification(NotificationBase):  # Not Verified
    """
    issue: AMLNG-???
    notification_type: Listing Owner
    As an user, I want to send a notification to the owners and org_steward for that listing's agency
    target: owners and org_steward for that listing's agency
    invoked: Directly
    """

    def modify_notification_before_save(self, notification_object):
        notification_object.listing = self.entity_dict['listing']

    def get_entity_id(self):
        return self.entity_dict['listing'].id

    def get_notification_db_type(self):
        return Notification.LISTING

    def get_group_target(self):
        return Notification.USER

    def get_target_list(self):
        current_listing = self.entity_dict['listing']

        target_set = set()

        for owner in current_listing.owners.filter(listing_notification_flag=True).all():
            target_set.add(owner)

        current_listing_agency_id = current_listing.agency.id

        for steward in Profile.objects.filter(stewarded_organizations__in=[current_listing_agency_id], listing_notification_flag=True).all():
            target_set.add(steward)

        return list(target_set)


class ListingPrivateStatusNotification(NotificationBase):
    """
    issue: AMLNG-383
    notification_type: ListingPrivateStatus
    description:
        As a owner, I want to notify users who have bookmarked my listing when the
        listing is changed from public to private and vice-versa
    permission constraint: Only APP_MALL_STEWARDs and ORG_STEWARDs or owners of listing can
    target: Users that bookmarked listing
    invoked: In-directly
    test_case:
        Bookmarked an app listing in my own org
        Went to Bookmarked App Listing Quick View Modal | Send Notifications | Sent a notification
        RESULTS - I received the notification
        Bookmarked an app listing that did not belong to the org I was in
        Went to Bookmarked App Listing  Quick View Modal | Send Notifications | Sent a notification
        RESULTS - I received the notification
    """

    def modify_notification_before_save(self, notification_object):
        notification_object.listing = self.entity_dict['listing']

    def get_entity_id(self):
        return self.entity_dict['listing'].id

    def get_notification_db_type(self):
        return Notification.LISTING

    def get_notification_db_subtype(self):
        return Notification.LISTING_PRIVATE_STATUS

    def get_target_list(self):
        owner_id_list = get_owners_for_bookmark_3_2(self.entity_dict['listing'])
        return Profile.objects.filter(id__in=owner_id_list, listing_notification_flag=True).all()

    def check_local_permission(self, entity):
        if self.sender_profile.highest_role() in ['APPS_MALL_STEWARD', 'ORG_STEWARD']:
            return True

        if self.sender_profile not in self.entity_dict['listing'].owners.all():
            raise errors.PermissionDenied('Cannot create a notification for a listing you do not own')
        else:
            return True
        return False


class PendingDeletionToOwnerNotification(NotificationBase):  # Not Verified
    """
    issue: AMLNG-170
    notification_type: PendingDeletionToOwner
    description:
        As an Owner I want to receive notice of whether my deletion request has been rejected
    target: Users that ___
    invoked: In-directly
    event_occurs:
        Listing DELETED - Steward approved deletion
            PENDING_DELETION --> DELETED
        User undeleted the listing - Steward rejects deletion
            PENDING_DELETION --> PENDING
    test_case:
        Logged on as jones
        Set Test Notification Listing to Pend for Deletion state
        Logged on as minitrue Org Content Steward- julia
        Approved the deletion
        Logged on as jones
        RESULTS The notification launched = Test Notification Listing listing was approved for deletion by steward
    """

    def modify_notification_before_save(self, notification_object):
        notification_object.listing = self.entity_dict['listing']

    def get_entity_id(self):
        return self.entity_dict['listing'].id

    def get_notification_db_type(self):
        return Notification.LISTING

    def get_notification_db_subtype(self):
        return Notification.PENDING_DELETION_TO_OWNER

    def get_target_list(self):
        current_listing = self.entity_dict['listing']
        return current_listing.owners.filter(listing_notification_flag=True).all().distinct()


class PendingDeletionToStewardNotification(NotificationBase):  # Not Verified
    """
    issue: AMLNG-173, AMLOS-490
    notification_type: PendingDeletionToSteward
        As an cs I want a notification if an owner has cancelled an app
        that was pending deletion
        as a cs, I want a notification if an owner pends a listing for deletion
    event_occurs:
        This event occurs when
            User undeleted the listing
                PENDING_DELETION --> PENDING
            User pends a listing for deletion
                ANY --> PENDING_DELETION
    test_case:
        Set Test Notification Listing to Pend for Deletion Status
        RESULTS - Notificaiton launched = Listing Owner has requested the deletion of Test Notification Listing listing
        Logged on as jones (owner of <Test Notification> Listing)
        Undeleted the Test Notification Listing
        Logged on as Org Content Steward - julia
        RESULTS - Notificaiton launched = Listing Owner cancelled deletion of Test Notification Listing listing
    """

    def modify_notification_before_save(self, notification_object):
        notification_object.listing = self.entity_dict['listing']

    def get_entity_id(self):
        return self.entity_dict['listing'].id

    def get_notification_db_type(self):
        return Notification.LISTING

    def get_notification_db_subtype(self):
        return Notification.PENDING_DELETION_TO_STEWARD

    def get_target_list(self):
        current_listing = self.entity_dict['listing']
        current_listing_agency_id = current_listing.agency.id
        target_set = set()

        for steward in Profile.objects.filter(stewarded_organizations__in=[current_listing_agency_id], listing_notification_flag=True).all():
            target_set.add(steward)

        for admin in Profile.objects.filter(user__groups__name='APPS_MALL_STEWARD', listing_notification_flag=True).all():
            target_set.add(admin)

        return list(target_set)


class PendingDeletionApprovedNotification(NotificationBase):
    """
    notification_type: PendingDeletionApproved
        As a listing owner I want a notification if a steward has approved the deletion of the listing
    event_occurs:
        This event occurs when
            Steward approves listing
                PENDING_DELETION --> DELETED
    test_case:
        Set Test Notification Listing to Pend for Deletion Status
        RESULTS - Notificaiton launched = Listing Owner has requested the deletion of Test Notification Listing listing
        Logged on as Org Content Steward - julia
        Approve the deletion requested
        Logged on as owner - jones
        RESULTS - Notificaiton launched = Listing Owner cancelled deletion of Test Notification Listing listing
    """

    def modify_notification_before_save(self, notification_object):
        notification_object.listing = self.entity_dict['listing']

    def get_entity_id(self):
        return self.entity_dict['listing'].id

    def get_notification_db_type(self):
        return Notification.LISTING

    def get_notification_db_subtype(self):
        return Notification.PENDING_DELETION_APPROVED

    def get_target_list(self):
        current_listing = self.entity_dict['listing']
        current_listing_agency_id = current_listing.agency.id
        target_set = set()

        for steward in Profile.objects.filter(stewarded_organizations__in=[current_listing_agency_id], listing_notification_flag=True).all():
            target_set.add(steward)

        for admin in Profile.objects.filter(user__groups__name='APPS_MALL_STEWARD', listing_notification_flag=True).all():
            target_set.add(admin)

        for owner in current_listing.owners.filter(listing_notification_flag=True).all().distinct():
            target_set.add(owner)

        return list(target_set)


class ListingSubmissionNotification(NotificationBase):
    """
    issue: AMLNG-376
    notification_type: ListingSubmission
    description:
        As a CS, I want to receive notification of Listings submitted for my organization
    target: Listing Agency ORG_STEWARDs
    invoked: In-directly
    event_occurs:
        This event occurs when
            User Submitted Listings
                IN_PROGRESS --> PENDING

        a = Listing.objects.last(); a.approval_status = Listing.IN_PROGRESS; a.save()
    test_case:
        Logged into Apps Mall as jones ( minitrue)
        Submitted a new listing using org minitrue.
        Logged into Apps mall as CS - julia (minitrue)
        RESULTS - Notification displays = Test Notification Listing listing was submitted
    """

    def modify_notification_before_save(self, notification_object):
        notification_object.listing = self.entity_dict['listing']

    def get_entity_id(self):
        return self.entity_dict['listing'].id

    def get_group_target(self):
        return Notification.ORG_STEWARD

    def get_notification_db_type(self):
        return Notification.LISTING

    def get_notification_db_subtype(self):
        return Notification.LISTING_NEW

    def get_target_list(self):
        current_listing = self.entity_dict['listing']
        current_listing_agency_id = current_listing.agency.id
        return Profile.objects.filter(stewarded_organizations__in=[current_listing_agency_id], listing_notification_flag=True).all().distinct()


class TagSubscriptionNotification(NotificationBase):  # Not Verified
    """
    issue: AMLNG-392
    notification_type: TagSubscription
        As a user, I want to receive notification when a Listing is added to a subscribed tag
    target: Users that ___
    invoked: In-directly
    """

    def modify_notification_before_save(self, notification_object):
        notification_object.listing = self.entity_dict['listing']

    def get_entity_id(self):
        return self.entity_dict['listing'].id

    def get_notification_db_type(self):
        return Notification.SUBSCRIPTION

    def get_notification_db_subtype(self):
        return Notification.SUBSCRIPTION_TAG

    def get_target_list(self):
        # entity: listing, metadata: entities
        subscription_entries = Subscription.objects.filter(entity_type='tag', entity_id__in=list(self.entity_dict['entities']))
        target_profiles = set()
        for subscription_entry in subscription_entries:
            target_profile = subscription_entry.target_profile
            if target_profile.subscription_notification_flag:
                target_profiles.add(target_profile)

        return list(target_profiles)


class CategorySubscriptionNotification(NotificationBase):  # Not Verified
    """
    issue: AMLNG-380
    notification_type: CategorySubscription
    description:
        As a user, I want to receive notification when a Listing is added to a subscribed category
    target: Users that are subscribed to category
    invoked: In-directly
    event_occurs:
        Should occur when a user submits a listing with a category and listing gets approved,
            it should send out notifications for users that have that category subscribed and has the Subscription Preference Flag to True
        Should occur when a published listing add new category,
            it should send out notifications for users that have that category subscribed and has the Subscription Preference Flag to True
    test_case:
        Logged on as jones
        Subscribed to Finance
        Logged on as big brother
        Add any Listing to Finance
        Logged on as jones
        RESULTS- Notification "A new listing in category Finance"
    """

    def modify_notification_before_save(self, notification_object):
        notification_object.listing = self.entity_dict['listing']

    def get_entity_id(self):
        return self.entity_dict['listing'].id

    def get_notification_db_type(self):
        return Notification.SUBSCRIPTION

    def get_notification_db_subtype(self):
        return Notification.SUBSCRIPTION_CATEGORY

    def get_target_list(self):
        # entity: listing, metadata: entities
        subscription_entries = Subscription.objects.filter(entity_type='category', entity_id__in=list(self.entity_dict['entities']))
        target_profiles = set()
        for subscription_entry in subscription_entries:
            target_profile = subscription_entry.target_profile
            if target_profile.subscription_notification_flag:
                target_profiles.add(target_profile)

        return list(target_profiles)


class StewardAppNotification(NotificationBase):
    """
    issue: AMLNG-745
    notification_type: StewardAppNotification
    description:
        A process to notify and instruct content stewards to review and update, as needed, current listing information for all listing in their organization.
        An admin has the ability to send out a notification to all Content Stewards, notifying them to review their org's Listings and make any necessary changes.
        Content Steward updates Listing as needed via Create New Listing Form (the usual means of updating listings)
        Content Steward and listing owner(s) are notified when listing has been updated and approve
    target: All ORG_STEWARDS
    permission constraint: Only APP_MALL_STEWARDs can send notifications
    invoked: Directly
    test_case:
        As bigbrother,
        Go to Center Settings (from the dropdown menu)
        Go to the Notifications Tab
        Select the 'Update Request' type
        See that the Notification text is populated with a default message (you can change this message if you like)
        Set expires on date
        Press send
        Login as david, julia, obrien and wsmith to make sure that they have received the message and that it has the link as detailed in acceptance criteria

        bigbrother should not receive the notification
        hodor should not receive the notification
        jones should not receive the notification
    """

    def modify_notification_before_save(self, notification_object):
        pass

    def get_entity_id(self):
        pass

    def get_notification_db_type(self):
        return Notification.SYSTEM

    def get_notification_db_subtype(self):
        return Notification.REVIEW_REQUEST

    def get_group_target(self):
        return Notification.ORG_STEWARD

    def get_target_list(self):
        target_set = set()
        agencies = Agency.objects.all()
        for steward in Profile.objects.filter(stewarded_organizations__in=agencies, listing_notification_flag=True).all():
            target_set.add(steward)

        return list(target_set)
