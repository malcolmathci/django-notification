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

        context = Context({})
        context.update({
            "recipient": recipient,
            "sender": sender,
            "notice": ugettext(notice_type.past_tense),
            'default_profile_photo': settings.DEFAULT_PROFILE_PHOTO,
        })
        context.update(extra_context)

        messages = self.get_formatted_messages((
            "full.html",
        ), notice_type.label, context)

        if 'target_url' in extra_context:
            target_url = extra_context['target_url']
        else:
            target_url = extra_context['target'].url if hasattr(extra_context['target'], 'url') else sender.get_absolute_url()
            if recipient == extra_context['target']:
                target_url = sender.get_absolute_url()

        Notice.objects.create(
            recipient=recipient,
            notice_type=notice_type,
            sender=sender,
            message=messages['full.html'],
            on_site=True,
            target_url=target_url
        )
