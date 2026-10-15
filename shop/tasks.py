import json
import logging
from celery import shared_task
from celery.utils.log import get_task_logger
from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone

logger = get_task_logger(__name__)


# ─── Core push task — sends to ONE user ───────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    name='shop.tasks.send_push_to_single_user'
)
def send_push_to_single_user_task(self, user_id, title, body, url='/'):
    """
    Celery task to send push notification to a single user.
    Retries up to 3 times on failure.
    """
    try:
        from pywebpush import webpush, WebPushException
        from shop.models import PushSubscription

        user = User.objects.get(id=user_id)
        subscriptions = PushSubscription.objects.filter(user=user)

        if not subscriptions.exists():
            logger.info(f"No subscriptions for user {user.email}")
            return {'status': 'skipped', 'reason': 'no subscriptions'}

        results = {'sent': 0, 'failed': 0, 'deleted': 0}

        for sub in subscriptions:
            try:
                webpush(
                    subscription_info=json.loads(sub.subscription_json),
                    data=json.dumps({
                        'title': title,
                        'body': body,
                        'url': url,
                        'icon': '/icons/icon-192x192.png',
                    }),
                    vapid_private_key=settings.VAPID_PRIVATE_KEY,
                    vapid_claims=settings.VAPID_CLAIMS,
                )
                results['sent'] += 1
                logger.info(f"Push sent to {user.email}")

            except WebPushException as e:
                results['failed'] += 1
                logger.error(f"Push failed for {user.email}: {e}")
                # Subscription expired — delete it
                if e.response and e.response.status_code == 410:
                    sub.delete()
                    results['deleted'] += 1

        return results

    except User.DoesNotExist:
        logger.error(f"User {user_id} not found")
        return {'status': 'error', 'reason': 'user not found'}

    except Exception as exc:
        logger.error(f"Task failed for user {user_id}: {exc}")
        # Retry the task
        raise self.retry(exc=exc, countdown=60)


# ─── Bulk push task — sends to MANY users in batches ──────────────────────────

@shared_task(
    bind=True,
    name='shop.tasks.send_bulk_push_notification'
)
def send_bulk_push_notification(
    self,
    user_ids,
    title,
    body,
    url='/',
    batch_size=None
):
    """
    Send push notifications to a list of users in batches.
    Each user gets their own sub-task for reliability.
    """
    if batch_size is None:
        batch_size = getattr(settings, 'PUSH_NOTIFICATION_BATCH_SIZE', 100)

    total = len(user_ids)
    logger.info(f"Starting bulk push to {total} users. Title: {title}")

    # Update task state so admin can see progress
    self.update_state(
        state='PROGRESS',
        meta={
            'total': total,
            'processed': 0,
            'sent': 0,
            'failed': 0,
        }
    )

    sent = 0
    failed = 0

    # Process in batches
    for i in range(0, total, batch_size):
        batch = user_ids[i:i + batch_size]

        for user_id in batch:
            try:
                # Fire individual task for each user
                # This way if one fails it doesn't affect others
                send_push_to_single_user_task.apply_async(
                    args=[user_id, title, body, url],
                    countdown=0,
                )
                sent += 1
            except Exception as e:
                failed += 1
                logger.error(f"Failed to queue push for user {user_id}: {e}")

        # Update progress after each batch
        self.update_state(
            state='PROGRESS',
            meta={
                'total': total,
                'processed': i + len(batch),
                'sent': sent,
                'failed': failed,
            }
        )

        logger.info(
            f"Batch {i // batch_size + 1} done. "
            f"Processed: {i + len(batch)}/{total}"
        )

    result = {
        'status': 'completed',
        'total': total,
        'queued': sent,
        'failed': failed,
        'completed_at': timezone.now().isoformat(),
    }
    logger.info(f"Bulk push complete: {result}")
    return result


# ─── Scheduled marketing task ─────────────────────────────────────────────────

@shared_task(name='shop.tasks.send_scheduled_marketing_push')
def send_scheduled_marketing_push(title, body, url='/', user_filter=None):
    """
    Scheduled marketing push — send to all subscribed users
    or filtered subset.

    user_filter options:
        None          → all subscribed users
        'marketing'   → only users with marketing_preference=True
        'all'         → everyone
    """
    from shop.models import PushSubscription, UserProfile

    try:
        if user_filter == 'marketing':
            # Only users who opted into marketing
            user_ids = list(
                UserProfile.objects.filter(
                    marketing_preference=True
                ).values_list('user__id', flat=True)
            )
        else:
            # All users with active subscriptions
            user_ids = list(
                PushSubscription.objects.values_list(
                    'user__id', flat=True
                ).distinct()
            )

        if not user_ids:
            logger.info("No users to send marketing push to")
            return {'status': 'skipped', 'reason': 'no users'}

        logger.info(
            f"Scheduling marketing push to {len(user_ids)} users"
        )

        # Fire bulk task
        send_bulk_push_notification.apply_async(
            args=[user_ids, title, body, url],
        )

        return {
            'status': 'queued',
            'user_count': len(user_ids)
        }

    except Exception as e:
        logger.error(f"Scheduled marketing push failed: {e}")
        raise


# ─── Cleanup expired subscriptions ────────────────────────────────────────────

@shared_task(name='shop.tasks.cleanup_expired_subscriptions')
def cleanup_expired_subscriptions():
    """
    Runs periodically to remove expired push subscriptions.
    Schedule this to run daily.
    """
    from shop.models import PushSubscription
    from pywebpush import webpush, WebPushException

    subscriptions = PushSubscription.objects.all()
    deleted_count = 0

    for sub in subscriptions:
        try:
            # Send empty ping to check if subscription is still valid
            webpush(
                subscription_info=json.loads(sub.subscription_json),
                data=json.dumps({'type': 'ping'}),
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims=settings.VAPID_CLAIMS,
            )
        except WebPushException as e:
            if e.response and e.response.status_code == 410:
                sub.delete()
                deleted_count += 1
        except Exception:
            pass

    logger.info(f"Cleaned up {deleted_count} expired subscriptions")
    return {'deleted': deleted_count}

# ─── Single order status update with push ─────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    name='shop.tasks.notify_order_status_change'
)
def notify_order_status_change(self, order_id, new_status, extra_info=None):
    """
    Send push notification when order status changes.
    Called from dispatch_order and update_order_status views.
    """
    try:
        from shop.models import Order, OrderStatus
        from shop.utils import send_push_to_user

        order = Order.objects.get(order_id=order_id)
        user = order.user

        status_notifications = {
            OrderStatus.READY_FOR_DISPATCH.value: {
                'title': 'Order ready! 📦',
                'body': f'Your M18 Foods order is packed and ready.',
            },
            OrderStatus.DISPATCHED.value: {
                'title': 'Your order is on the way! 🚚',
                'body': (
                    f'Order dispatched via {extra_info}.'
                    if extra_info
                    else f'Order is on its way to you.'
                ),
            },
            OrderStatus.DELIVERED.value: {
                'title': 'Order delivered! ✅',
                'body': f'Order has been delivered. Enjoy your food!',
            },
            OrderStatus.CANCELED.value: {
                'title': 'Order cancelled ❌',
                'body': f'Order has been cancelled. Contact us for help.',
            },
            OrderStatus.RETURNED.value: {
                'title': 'Order returned 🔄',
                'body': f'Order has been marked as returned. We will process it soon.',
            },
        }

        notification = status_notifications.get(new_status)
        if not notification:
            logger.info(f"No notification configured for status: {new_status}")
            return {'status': 'skipped', 'reason': 'no notification for status'}

        send_push_to_user(
            user=user,
            title=notification['title'],
            body=notification['body'],
            url=f'/account/order-history/{order_id}'
        )

        logger.info(f"Status notification sent for order {order_id} → {new_status}")
        return {'status': 'sent', 'order_id': str(order_id), 'new_status': new_status}

    except Exception as exc:
        logger.error(f"notify_order_status_change failed: {exc}")
        raise self.retry(exc=exc, countdown=60)


# ─── Bulk order complete + notify ─────────────────────────────────────────────

@shared_task(
    bind=True,
    name='shop.tasks.complete_orders_and_notify'
)
def complete_orders_and_notify(self, order_ids):
    """
    Complete multiple orders and send push notifications.
    Called from admin complete_and_notify_users action.
    """
    from shop.models import Order, OrderStatus
    from shop.utils import send_push_to_user

    results = {
        'total': len(order_ids),
        'completed': 0,
        'notified': 0,
        'failed': 0,
    }

    self.update_state(
        state='PROGRESS',
        meta=results
    )

    for order_id in order_ids:
        try:
            order = Order.objects.get(order_id=order_id)

            # 1. Update status
            order.status = OrderStatus.DELIVERED.value
            order.save()
            results['completed'] += 1

            # 2. Fire individual push task per order
            notify_order_status_change.apply_async(
                args=[order_id, OrderStatus.DELIVERED.value],
                countdown=0,
            )
            results['notified'] += 1

        except Order.DoesNotExist:
            logger.error(f"Order {order_id} not found")
            results['failed'] += 1
        except Exception as e:
            logger.error(f"Failed to complete order {order_id}: {e}")
            results['failed'] += 1

        # Update progress
        self.update_state(state='PROGRESS', meta=results)

    logger.info(f"complete_orders_and_notify done: {results}")
    return results