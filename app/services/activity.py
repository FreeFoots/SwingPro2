"""
业务统计服务

提供：
1. 记录业务行为
2. 统计查询
"""

from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.models.activity import ActivityLog, ActivityAction
from app.core.security import now_bj


# ============== 记录业务行为 ==============

def log_activity(
    db: Session,
    category: str,
    action: str,
    user_id: str = None,
    user_telephone: str = None,
    user_role: str = None,
    target_type: str = None,
    target_id: str = None,
    detail: dict = None,
    ip_address: str = None,
    user_agent: str = None,
    success: bool = True,
    error_msg: str = None,
):
    """
    记录一条业务行为日志

    Args:
        category: 分类 (auth/video/user)
        action: 具体行为
        user_id: 操作者用户ID
        user_telephone: 手机号（会自动脱敏）
        user_role: 用户角色
        target_type: 操作对象类型
        target_id: 操作对象ID
        detail: 详细信息字典
        ip_address: 客户端IP
        user_agent: 客户端UA
        success: 是否成功
        error_msg: 失败原因
    """
    # 手机号脱敏
    masked_tel = None
    if user_telephone and len(user_telephone) >= 7:
        masked_tel = user_telephone[:3] + "****" + user_telephone[-4:]

    log = ActivityLog(
        category=category,
        action=action,
        user_id=user_id,
        user_telephone=masked_tel,
        user_role=user_role,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
        ip_address=ip_address,
        user_agent=user_agent[:200] if user_agent else None,
        success=1 if success else 0,
        error_msg=error_msg[:500] if error_msg else None,
    )
    db.add(log)
    db.commit()
    return log


# ============== 系统资源采集 ==============

# ============== 统计查询 ==============

def get_activity_summary(
    db: Session,
    start_date: datetime = None,
    end_date: datetime = None,
) -> dict:
    """
    获取行为统计汇总

    返回各分类、各行为的数量统计
    """
    if not start_date:
        start_date = now_bj() - timedelta(days=7)
    if not end_date:
        end_date = now_bj()

    # 按分类统计
    category_stats = db.query(
        ActivityLog.category,
        func.count(ActivityLog.id).label("count"),
        func.sum(ActivityLog.success).label("success_count"),
    ).filter(
        ActivityLog.created_at.between(start_date, end_date)
    ).group_by(ActivityLog.category).all()

    # 按行为统计
    action_stats = db.query(
        ActivityLog.category,
        ActivityLog.action,
        func.count(ActivityLog.id).label("count"),
    ).filter(
        ActivityLog.created_at.between(start_date, end_date)
    ).group_by(ActivityLog.category, ActivityLog.action).all()

    return {
        "period": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
        },
        "by_category": [
            {
                "category": row.category,
                "total": row.count,
                "success": row.success_count or 0,
                "failed": row.count - (row.success_count or 0),
            }
            for row in category_stats
        ],
        "by_action": [
            {
                "category": row.category,
                "action": row.action,
                "count": row.count,
            }
            for row in action_stats
        ],
    }


def get_daily_stats(
    db: Session,
    category: str = None,
    days: int = 7,
) -> list:
    """
    获取每日统计趋势

    Args:
        category: 可选，按分类筛选
        days: 统计天数
    """
    start_date = now_bj() - timedelta(days=days)

    query = db.query(
        func.date(ActivityLog.created_at).label("date"),
        func.count(ActivityLog.id).label("count"),
    ).filter(
        ActivityLog.created_at >= start_date
    )

    if category:
        query = query.filter(ActivityLog.category == category)

    results = query.group_by(func.date(ActivityLog.created_at)).order_by("date").all()

    return [{"date": str(row.date), "count": row.count} for row in results]


def get_recent_activities(
    db: Session,
    category: str = None,
    action: str = None,
    limit: int = 50,
) -> list:
    """获取最近的行为记录"""
    query = db.query(ActivityLog)

    if category:
        query = query.filter(ActivityLog.category == category)
    if action:
        query = query.filter(ActivityLog.action == action)

    logs = query.order_by(ActivityLog.created_at.desc()).limit(limit).all()

    return [
        {
            "id": log.id,
            "time": log.created_at.isoformat() if log.created_at else None,
            "category": log.category,
            "action": log.action,
            "user_telephone": log.user_telephone,
            "user_role": log.user_role,
            "target_type": log.target_type,
            "target_id": log.target_id,
            "detail": log.detail,
            "ip": log.ip_address,
            "success": log.success == 1,
            "error": log.error_msg,
        }
        for log in logs
    ]


def get_sensitive_activities(
    db: Session,
    start_date: datetime = None,
    end_date: datetime = None,
    limit: int = 100,
) -> list:
    """
    获取敏感操作记录

    包括：修改密码、修改权限、修改场地、注册等
    """
    sensitive_actions = [
        ActivityAction.REGISTER,
        ActivityAction.PASSWORD_CHANGE,
        ActivityAction.PASSWORD_RESET,
        ActivityAction.ROLE_CHANGE,
        ActivityAction.USER_DISABLE,
        ActivityAction.USER_ENABLE,
        ActivityAction.INVITE_CREATE,
    ]

    query = db.query(ActivityLog).filter(
        ActivityLog.action.in_(sensitive_actions)
    )

    if start_date:
        query = query.filter(ActivityLog.created_at >= start_date)
    if end_date:
        query = query.filter(ActivityLog.created_at <= end_date)

    logs = query.order_by(ActivityLog.created_at.desc()).limit(limit).all()

    return [
        {
            "id": log.id,
            "time": log.created_at.isoformat() if log.created_at else None,
            "action": log.action,
            "user_telephone": log.user_telephone,
            "user_role": log.user_role,
            "target_type": log.target_type,
            "target_id": log.target_id,
            "detail": log.detail,
            "ip": log.ip_address,
            "success": log.success == 1,
            "error": log.error_msg,
        }
        for log in logs
    ]
