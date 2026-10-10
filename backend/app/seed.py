from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RiskListItem, UserProfile
from app.modules.detection.service import detect_transaction
from app.modules.strategy.service import get_active_strategy


def seed_demo_data(db: Session) -> None:
    get_active_strategy(db)
    if not db.execute(select(UserProfile).where(UserProfile.user_id == "U1001")).scalars().first():
        db.add_all(
            [
                UserProfile(user_id="U1001", account_name="张三", phone_hash="138****9281", risk_level="LOW", last_login_location="上海"),
                UserProfile(user_id="U2002", account_name="王五", phone_hash="155****0023", risk_level="MEDIUM", last_login_location="深圳"),
                UserProfile(user_id="U9009", account_name="高危账户", phone_hash="177****2198", risk_level="HIGH", last_login_location="成都"),
            ]
        )
    if not db.execute(select(RiskListItem).where(RiskListItem.item_value == "U9009")).scalars().first():
        db.add_all(
            [
                RiskListItem(
                    item_id="RL-black-user-001",
                    list_type="USER",
                    item_value="U9009",
                    risk_level="L3",
                    description="高危欺诈主体名单",
                ),
                RiskListItem(
                    item_id="RL-device-001",
                    list_type="DEVICE",
                    item_value="DEV-RISK-X",
                    risk_level="L2",
                    description="设备复用观察名单",
                ),
            ]
        )
    db.commit()
    if not db.execute(select(RiskListItem)).scalars().first():
        db.commit()
    if not db.execute(select(RiskListItem).where(RiskListItem.item_value == "U9009")).scalars().first():
        db.commit()
    # Seed one REVIEW and one BLOCK case for immediate UI demonstration.
    from app.models import Transaction

    existing = db.execute(select(Transaction).where(Transaction.transaction_id == "TX-DEMO-REVIEW")).scalars().first()
    if not existing:
        detect_transaction(
            db,
            {
                "transaction_id": "TX-DEMO-REVIEW",
                "user_id": "U2002",
                "amount": 368000,
                "channel": "APP",
                "device_id": "DEV-2002",
                "merchant_id": "MCH-NORMAL-001",
                "location": "哈尔滨",
                "night_operation": True,
                "context_clues": ["用户申诉称是本人真实交易，已提供交易凭证与聊天记录截图"],
            },
            "TR-DEMO-REVIEW",
        )
    existing = db.execute(select(Transaction).where(Transaction.transaction_id == "TX-DEMO-BLOCK")).scalars().first()
    if not existing:
        detect_transaction(
            db,
            {
                "transaction_id": "TX-DEMO-BLOCK",
                "user_id": "U9009",
                "amount": 1240000,
                "channel": "WEB",
                "device_id": "DEV-RISK-X",
                "merchant_id": "MCH-RISK-001",
                "location": "上海",
            },
            "TR-DEMO-BLOCK",
        )
    # 冲突演示：无画像用户的夜间小额转账触发行为 Agent 高分告警，
    # 仲裁识别其为低置信离群意见并降权，最终按融合分放行（误报消减案例）。
    existing = db.execute(select(Transaction).where(Transaction.transaction_id == "TX-DEMO-CONFLICT")).scalars().first()
    if not existing:
        detect_transaction(
            db,
            {
                "transaction_id": "TX-DEMO-CONFLICT",
                "user_id": "U3003",
                "amount": 3000,
                "channel": "私人转账",
                "device_id": "DEV-2002",
                "merchant_id": "MCH-NORMAL-001",
                "location": "北京",
                "night_operation": True,
            },
            "TR-DEMO-CONFLICT",
        )
    # 已复核演示案例：让 RAG 案例库与学习闭环开箱即有数据（幂等，重复 seed 自动跳过）。
    # REVIEW 案复核为误报（申诉通过）、BLOCK 案确认欺诈（申诉驳回）。
    from app.models import Alert, Transaction as TxModel
    from app.modules.cases.service import review_case

    def _seed_reviewed_case(transaction_id: str, verdict: str, remark: str) -> None:
        transaction = db.execute(select(TxModel).where(TxModel.transaction_id == transaction_id)).scalars().first()
        if not transaction or not transaction.decision:
            return
        alert = db.execute(select(Alert).where(Alert.transaction_id == transaction_id)).scalars().first()
        if not alert or not alert.review_case or alert.review_case.status == "COMPLETED":
            return
        review_case(
            db,
            {"case_id": alert.review_case.case_id, "review_result": verdict, "reviewer": "seed", "remark": remark},
            f"TR-SEED-REVIEW-{transaction_id}",
            actor="seed",
            actor_role="ADMIN",
        )
        db.commit()

    _seed_reviewed_case("TX-DEMO-REVIEW", "误报", "演示案例：用户已提供交易凭证，判定为误拦，申诉通过。")
    _seed_reviewed_case("TX-DEMO-BLOCK", "欺诈", "演示案例：命中高危名单且大额夜间操作，确认欺诈。")
