from django.conf import settings
from django.template import Context
from django.utils.translation import ugettext

from notification import backends


class OnSiteBackend(backends.BaseBackend):
    spam_sensitivity = 0

    def can_send(self, user, notice_type):
        can_send = super(OnSiteBackend, self).can_send(user, notice_type)
        if can_send:
            return True
        return False

    def deliver(self, recipient, sender, notice_type, extra_context):
        from notification.models import Notice

        if 'disallow_notice' in extra_context:
            if 'onsite' in extra_context['disallow_notice']:
                return

        if 'pm_message' in extra_context:
            sender = extra_context['pm_message'].sender

        target_url = self.get_target_url(extra_context, sender, recipient)

        context = Context({})
        context.update({
            "recipient": recipient,
            "sender": sender,
            "notice": ugettext(notice_type.past_tense),
            'default_profile_photo': getattr(settings, 'DEFAULT_PROFILE_PHOTO', None),
            'target_url': target_url,
        })
        context.update(extra_context)

        try:
            messages = self.get_formatted_messages((
                "full.html",
            ), context['app_label'], context)

        except:
            messages = self.get_formatted_messages((
                "full.html",
            ), notice_type.label, context)

        if sender.__class__.__name__ == 'Company':
            sender = sender.admin_primary if sender.admin_primary else sender.created_by

        Notice.objects.create(
            recipient=recipient,
            notice_type=notice_type,
            sender=sender,
            message=messages['full.html'],
            on_site=True,
            target_url=target_url
        )
