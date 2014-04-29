from notification.models import Notice


def notification(request):
    if request.user.is_authenticated():
        return {
            "notice_unseen_count": Notice.objects.unseen_count_for(request.user, on_site=True),
            "notifications": Notice.objects.filter(recipient=request.user.id)
        }
    else:
        return {}