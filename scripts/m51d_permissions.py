"""Real role matrix and final-build committed-response-loss/restart checks."""
import json
import os
import uuid
from decimal import Decimal
os.environ["DEEPSEEKDOC_DEMO"]="1"
from demo import guard
from local_stack import RUN,query
from live_smoke import check
from m51_live_smoke import PaymentSmoke
from m51d_fault_proxy import arm,stop_java,start_java


def main():
    guard()
    f=json.loads((RUN/"m51c-browser.json").read_text(encoding="utf-8"))
    s=PaymentSmoke(); checks=[]
    try:
        s.product=f["product"]
        a=s.request("POST","/api/auth/login",data=f["a"])["token"]
        oid=f.get("orders",{}).get("normal") or f["longOrder"]
        read=s.request("POST","/api/auth/agent-token",a)["token"]
        prep=s.request("POST","/api/auth/order-agent-token",a,{"items":[{"medicineId":s.product,"quantity":1}]})["token"]
        endpoints=[("checkout","POST",f"/api/order-drafts/{f['drafts']['normal']}/checkout",{"expectedVersion":2}),
            ("private_order","GET",f"/api/orders/{oid}",None),
            ("authorize","POST",f"/api/orders/{oid}/payment-authorizations",{"expectedVersion":1,"password":f["pin"]}),
            ("revoke","DELETE",f"/api/orders/{oid}/payment-authorizations?authorizationId={uuid.uuid4()}",None),
            ("pay","POST",f"/api/orders/{oid}/pay",{"expectedVersion":1}),
            ("close","POST",f"/api/orders/{oid}/close",{"expectedVersion":2})]
        for role,token in (("AGENT_READ",read),("AGENT_ORDER_PREPARE",prep)):
            for name,method,path,body in endpoints:
                response=s.http.request(method,s.base+path,json=body,headers={"Authorization":"Bearer "+token,"Idempotency-Key":str(uuid.uuid4()),"X-Payment-Authorization":"A"*43})
                check(response.status_code==403,"Agent reached USER-only "+name)
                checks.append({"role":role,"operation":name,"status":403,"passed":True})
        b=s.request("POST","/api/auth/login",data=f["b"])["token"]
        s.request("GET",f"/api/orders/{oid}",b,expected=404)
        checks.append({"operation":"foreign_USER_order","status":404,"passed":True})
        before=query(s.conn,"SELECT balance,points FROM users WHERE user_id=%s",(f["a"]["userId"],))[0]
        s.pin=f["pin"]
        final=s.checkout(a,quantity=1)["orderId"]; cap=s.grant(a,final)
        arm("drop_pay_response",final)
        dropped=s.http.post(s.base+f"/api/orders/{final}/pay",json={"expectedVersion":1},headers={"Authorization":"Bearer "+a,"Idempotency-Key":"m51d-final-response-loss","X-Payment-Authorization":cap["token"]})
        check(dropped.status_code>=500,"Response loss did not reach HTTP client")
        check(query(s.conn,"SELECT payment_status FROM orders WHERE id=%s",(final,))[0][0]=="PAID","Dropped response did not follow commit")
        stop_java()
        unavailable=s.http.get(s.base+f"/api/orders/{final}",headers={"Authorization":"Bearer "+a})
        check(unavailable.status_code==503,"Stopped Java was unexpectedly available")
        start_java()
        recovered=s.request("GET",f"/api/orders/{final}?paymentRequestKey=m51d-final-response-loss",a)
        check(recovered["paymentStatus"]=="PAID" and recovered["requestOutcome"]["status"]=="SUCCEEDED","Final-build recovery failed")
        first=s.pay(a,final,cap,key="m51d-final-response-loss")
        second=s.pay(a,final,cap,key="m51d-explicit-replay")
        check(first==second==recovered["payment"],"Receipt replay changed")
        after=query(s.conn,"SELECT balance,points FROM users WHERE user_id=%s",(f["a"]["userId"],))[0]
        check(before[0]-after[0]==Decimal("0.10") and before[1]==after[1],"Repeated recovery changed money/points")
        check(query(s.conn,"SELECT COUNT(*) FROM payment_records WHERE order_id=%s",(final,))[0][0]==1,"Duplicate final-build payment")
        checks.extend([{"operation":name,"passed":True} for name in ("final_build_commit_response_loss","final_build_restart_recovery","explicit_receipt_replay_debits_once")])
        s.request("POST","/api/auth/logout",a); s.request("POST","/api/auth/logout",b)
        return {"passed":True,"checks":checks,"count":len(checks),"realHTTP":True,"realMySQL":True,"syntheticOnly":True}
    finally:
        s.http.close(); s.conn.close()


if __name__=="__main__":
    try: report=main()
    except Exception as exc: report={"passed":False,"failure":type(exc).__name__+": "+str(exc)}
    (RUN/"m51d-permissions-recovery.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report)); raise SystemExit(0 if report["passed"] else 1)
