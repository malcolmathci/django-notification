from __future__ import unicode_literals
from __future__ import print_function

import base64
import datetime

from django.db import models
from django.db.models.query import QuerySet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import get_language, activate
from django.utils.encoding import python_2_unicode_compatible
from django.utils.six.moves import cPickle as pickle  # pylint: disable-msg=F
from django.contrib.auth.models import User
from django.core.urlresolvers import reverse

from .compat import AUTH_USER_MODEL

from notification import backends


DEFAULT_QUEUE_ALL = False
QUEUE_ALL = getattr(settings, "NOTIFICATION_QUEUE_ALL", DEFAULT_QUEUE_ALL)
NOTIFICATION_BACKENDS = backends.load_backends()
NOTICE_MEDIA, NOTICE_MEDIA_DEFAULTS = backends.load_media_defaults(
    backends=NOTIFICATION_BACKENDS
)
STATE_TYPES = (
    (-1, _('Deleted')),
    (0, _('Draft')),
    (1, _('Published')),
)

class LanguageStoreNotAvailable(Exception):
    pass


def create_notice_type(label, display, description, **kwargs):
    NoticeType.create(label, display, description, **kwargs)


@python_2_unicode_compatible
class NoticeType(models.Model):

    label = models.CharField(_("label"), max_length=40)
    display = models.CharField(_("display"), max_length=50)
    past_tense = models.CharField(_("Past Tense"), max_length=100)
    description = models.TextField(_("description"))

    # by default only on for media with sensitivity less than or equal to this number
    default = models.IntegerField(_("default"), default=0)

    state = models.SmallIntegerField(verbose_name=_('Publish state'), choices=STATE_TYPES, default=1)

    def __str__(self):
        return self.label

    class Meta:
        verbose_name = _("notice type")
        verbose_name_plural = _("notice types")

    @classmethod
    def create(cls, label, display, description, past_tense=None, default=2, verbosity=1):
        """
        Creates a new NoticeType.

        This is intended to be used by other apps as a post_syncdb manangement step.
        """
        if not past_tense:
            past_tense = display
        try:
            notice_type = cls._default_manager.get(label=label)
            updated = False
            if display != notice_type.display:
                notice_type.display = display
                updated = True
            if past_tense != notice_type.past_tense:
                notice_type.past_tense = past_tense
                updated = True
            if description != notice_type.description:
                notice_type.description = description
                updated = True
            if default != notice_type.default:
                notice_type.default = default
                updated = True
            if updated:
                notice_type.save()
                if verbosity > 1:
                    print("Updated %s NoticeType" % label)
        except cls.DoesNotExist:
            cls(label=label, display=display, past_tense=past_tense, description=description, default=default).save()
            if verbosity > 1:
                print("Created %s NoticeType" % label)


class NoticeSetting(models.Model):
    """
    Indicates, for a given user, whether to send notifications
    of a given type to a given medium.
    """

    user = models.ForeignKey(AUTH_USER_MODEL, verbose_name=_("user"))
    notice_type = models.ForeignKey(NoticeType, verbose_name=_("notice type"))
    medium = models.CharField(_("medium"), max_length=1, choices=NOTICE_MEDIA)
    send = models.BooleanField(_("send"))

    class Meta:
        verbose_name = _("notice setting")
        verbose_name_plural = _("notice settings")
        unique_together = ("user", "notice_type", "medium")

    @classmethod
    def for_user(cls, user, notice_type, medium):
        try:
            return cls._default_manager.get(user=user, notice_type=notice_type, medium=medium)
        except cls.DoesNotExist:
            default = (NOTICE_MEDIA_DEFAULTS[medium] <= notice_type.default)
            setting = cls(user=user, notice_type=notice_type, medium=medium, send=default)
            setting.save()
            return setting


class NoticeManager(models.Manager):

    def notices_for(self, user, archived=False, unseen=None, on_site=None, sent=False):
        """
        returns Notice objects for the given user.

        If archived=False, it only include notices not archived.
        If archived=True, it returns all notices for that user.

        If unseen=None, it includes all notices.
        If unseen=True, return only unseen notices.
        If unseen=False, return only seen notices.
        """
        if sent:
            lookup_kwargs = {"sender": user}
        else:
            lookup_kwargs = {"recipient": user}
        qs = self.filter(**lookup_kwargs)
        if not archived:
            self.filter(archived=archived)
        if unseen is not None:
            qs = qs.filter(unseen=unseen)
        if on_site is not None:
            qs = qs.filter(on_site=on_site)
        return qs

    def unseen_count_for(self, recipient, **kwargs):
        """
        returns the number of unseen notices for the given user but does not
        mark them seen
        """
        return self.notices_for(recipient, unseen=True, **kwargs).count()

    def received(self, recipient, **kwargs):
        """
        returns notices the given recipient has recieved.
        """
        kwargs["sent"] = False
        return self.notices_for(recipient, **kwargs)

    def sent(self, sender, **kwargs):
        """
        returns notices the given sender has sent
        """
        kwargs["sent"] = True
        return self.notices_for(sender, **kwargs)


class Notice(models.Model):

    recipient = models.ForeignKey(AUTH_USER_MODEL, related_name="recieved_notices", verbose_name=_("recipient"))
    sender = models.ForeignKey(AUTH_USER_MODEL, null=True, related_name="sent_notices", verbose_name=_("sender"))
    message = models.TextField(_("message"))
    notice_type = models.ForeignKey(NoticeType, verbose_name=_("notice type"))
    added = models.DateTimeField(_("added"), auto_now_add=True, editable=False)
    unseen = models.BooleanField(_("unseen"), default=True)
    archived = models.BooleanField(_("archived"), default=False)
    on_site = models.BooleanField(_("on site"))
    target_url = models.URLField(_("target url"), null=True, blank=True)

    objects = NoticeManager()

    def __unicode__(self):
        return self.message

    def archive(self):
        self.archived = True
        self.save()

    def is_unseen(self):
        """
        returns value of self.unseen but also changes it to false.

        Use this in a template to mark an unseen notice differently the first
        time it is shown.
        """
        unseen = self.unseen
        if unseen:
            self.unseen = False
            self.save()
        return unseen

    class Meta:
        ordering = ["-added"]
        verbose_name = _("notice")
        verbose_name_plural = _("notices")

    def get_absolute_url(self):
        return reverse("notification_notice", args=[str(self.pk)])


class NoticeLastSeen(models.Model):
    recipient = models.OneToOneField(AUTH_USER_MODEL, related_name="notices_seen", verbose_name=_("recipient"))
    notice = models.ForeignKey(Notice)
    seen = models.DateTimeField(_("seen"), auto_now=True, editable=False)


class NoticeQueueBatch(models.Model):
    """
    A queued notice.
    Denormalized data for a notice.
    """
    pickled_data = models.TextField()


def get_notification_language(user):
    """
    Returns site-specific notification language for this user. Raises
    LanguageStoreNotAvailable if this site does not use translated
    notifications.
    """

    if getattr(settings, "NOTIFICATION_LANGUAGE_MODULE", False):
        try:
            app_label, model_name = settings.NOTIFICATION_LANGUAGE_MODULE.split(".")
            model = models.get_model(app_label, model_name)
            # pylint: disable-msg=W0212
            language_model = model._default_manager.get(user__id__exact=user.id)
            if hasattr(language_model, "default_language"):
                return language_model.default_language
        except (ImportError, ImproperlyConfigured, model.DoesNotExist):
            raise LanguageStoreNotAvailable
    else:
        try:
            language_model = User.objects.get(id=user.id)
            if not hasattr(language_model, "user_profile"):
                raise LanguageStoreNotAvailable
            language_model = language_model.user_profile
            if hasattr(language_model, "default_language"):
                return language_model.default_language
        except (ImportError, ImproperlyConfigured, User.DoesNotExist):
            raise LanguageStoreNotAvailable


def send_now(users, label, extra_context=None, sender=None):
    """
    Creates a new notice.

    This is intended to be how other apps create new notices.

    notification.send(user, "friends_invite_sent", {
        "spam": "eggs",
        "foo": "bar",
    })
    """

    sent = False
    if extra_context is None:
        extra_context = {}

    notice_type = NoticeType.objects.get(label=label)

    current_language = get_language()

    for user in users:
        # get user language for user from language store defined in
        # NOTIFICATION_LANGUAGE_MODULE setting
        try:
            language = get_notification_language(user)
        except LanguageStoreNotAvailable:
            language = None

        if language is not None:
            # activate the user's language
            activate(language)
            # activate('ru')

            if 'target' in extra_context and hasattr(extra_context['target'], 'translations'):
                try:
                    extra_context['target'].title = extra_context['target'].translations.get(language_code='ru').title
                except:
                    pass


        for backend in NOTIFICATION_BACKENDS.values():
            if backend.can_send(user, notice_type):
                if ('disallow_notice' in extra_context
                    and not [True for b_end in extra_context['disallow_notice'] if b_end in NOTIFICATION_BACKENDS.keys()])\
                        or 'disallow_notice' not in extra_context:
                    backend.deliver(user, sender, notice_type, extra_context)
                    sent = True

    # reset environment to original language
    activate(current_language)
    return sent


def send(*args, **kwargs):
    """
    A basic interface around both queue and send_now. This honors a global
    flag NOTIFICATION_QUEUE_ALL that helps determine whether all calls should
    be queued or not. A per call ``queue`` or ``now`` keyword argument can be
    used to always override the default global behavior.
    """
    queue_flag = kwargs.pop("queue", False)
    now_flag = kwargs.pop("now", False)
    assert not (queue_flag and now_flag), "'queue' and 'now' cannot both be True."
    if queue_flag:
        return queue(*args, **kwargs)
    elif now_flag:
        return send_now(*args, **kwargs)
    else:
        if QUEUE_ALL:
            return queue(*args, **kwargs)
        else:
            return send_now(*args, **kwargs)


def queue(users, label, extra_context=None, sender=None):
    """
    Queue the notification in NoticeQueueBatch. This allows for large amounts
    of user notifications to be deferred to a seperate process running outside
    the webserver.
    """
    if extra_context is None:
        extra_context = {}
    if isinstance(users, QuerySet):
        users = [row["pk"] for row in users.values("pk")]
    else:
        users = [user.pk for user in users]
    notices = []
    for user in users:
        notices.append((user, label, extra_context, sender))
    NoticeQueueBatch(pickled_data=base64.b64encode(pickle.dumps(notices))).save()
