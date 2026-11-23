"""Read-only reconciliation of the registered fault-test accounts before scoped cleanup."""
import json
import os
from decimal import Decimal
os.environ["DEEPSEEKDOC_DEMO"]="1"
from demo import guard
from local_stack import RUN,database,query,target_fingerprint


def audit():
    values=guard()
    f=json.loads((RUN/"m51c-browser.json").read_text(encoding="utf-8"))
    if f["targetFingerprint"]!=target_fingerprint(values): raise RuntimeError("Fault fixture target mismatch")
    names=(f["a"]["userId"],f["b"]["userId"])
    if not all(n.startswith(f["prefix"]+"_") for n in names): raise RuntimeError("Fault fixture owner mismatch")
    with database(values) as db:
        funds=query(db,"SELECT SUM(balance),SUM(points) FROM users WHERE user_id IN (%s,%s)",names)[0]
        ledger=query(db,"SELECT COALESCE(SUM(t.amount),0),COALESCE(SUM(t.points_change),0),COUNT(*) FROM transactions t JOIN users u ON u.id=t.user_id WHERE u.user_id IN (%s,%s) AND t.type='purchase'",names)[0]
        paid=query(db,"SELECT COUNT(*),COALESCE(SUM(o.total_price),0) FROM orders o JOIN users u ON u.id=o.user_id WHERE u.user_id IN (%s,%s) AND o.payment_status='PAID'",names)[0]
        records=query(db,"SELECT COUNT(*) FROM payment_records p JOIN users u ON u.id=p.user_id WHERE u.user_id IN (%s,%s)",names)[0][0]
        bad=query(db,"SELECT COUNT(*) FROM orders o JOIN users u ON u.id=o.user_id LEFT JOIN payment_records p ON p.order_id=o.id LEFT JOIN transactions t ON t.id=p.ledger_id WHERE u.user_id IN (%s,%s) AND o.payment_status='PAID' AND (p.id IS NULL OR t.id IS NULL OR p.user_id<>o.user_id OR t.user_id<>o.user_id OR t.related_id<>o.id OR t.type<>'purchase' OR p.amount<>o.total_price OR t.amount<>-p.amount OR t.points_change<>FLOOR(p.amount))",names)[0][0]
        quantities=query(db,"SELECT COALESCE(SUM(i.quantity),0) FROM order_items i JOIN orders o ON o.id=i.order_id JOIN users u ON u.id=o.user_id WHERE u.user_id IN (%s,%s) AND o.payment_status='PAID' AND i.medicine_id=%s",names+(f["product"],))[0][0]
        stock=query(db,"SELECT stock FROM medicines WHERE id=%s",(f["product"],))[0][0]
        requests=query(db,"SELECT status,rejection_code FROM payment_operation_requests WHERE target_id=%s AND operation='PAY' ORDER BY created_at",(f["orders"]["d_abort"],))
        active=query(db,"SELECT COUNT(*) FROM payment_authorizations p JOIN users u ON u.id=p.user_id WHERE u.user_id IN (%s,%s) AND p.status='ACTIVE'",names)[0][0]
    assert funds[0]==Decimal(100)+ledger[0] and funds[1]==ledger[1]
    assert paid[0]==records==ledger[2] and paid[1]==-ledger[0] and bad==0
    assert stock==100-quantities and active==0
    assert ("REJECTED","PAYMENT_ATTEMPT_EXPIRED") in requests and ("SUCCEEDED",None) in requests
    events=[json.loads(line) for line in (RUN/"m51d-fault-events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(e["event"]=="abort_kill_completed" for e in events)
    assert sum(e["event"]=="committed_response_dropped" for e in events)>=2
    scoped=[e for e in events if e["event"]=="scoped_late_revoke"]
    assert len(scoped)>=2 and all(e["originalOwner"] and e["authorizationIdSpecified"] for e in scoped)
    assert any(e.get("mode")=="delay_read_unauthorized" for e in events)
    audit={"passed":True,"syntheticOnly":True,"normalDatabaseChanged":False,"paidOrders":paid[0],"paymentRecords":records,"purchaseLedgers":ledger[2],"purchaseTotal":str(paid[1]),"remainingWalletBalance":str(funds[0]),"pointsAwarded":int(funds[1]),"inventoryDeducted":int(quantities),"inventoryRemaining":stock,"brokenFinancialLinks":bad,"activeAuthorizations":active,"abortedOldRequestRejected":True,"newPaymentExplicitlySucceeded":True}
    (RUN/"m51d-financial-audit.json").write_text(json.dumps(audit,indent=2),encoding="utf-8")
    return audit


if __name__=="__main__": print(json.dumps(audit()))
