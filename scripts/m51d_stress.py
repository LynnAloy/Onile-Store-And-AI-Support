"""Repeated real-HTTP/MySQL invariants, exclusively owned synthetic fixtures."""
import concurrent.futures
import json
import os
import uuid
from decimal import Decimal

os.environ["DEEPSEEKDOC_DEMO"] = "1"
from demo import guard
from local_stack import RUN, query
from live_smoke import check
from m51_live_smoke import PaymentSmoke


class Stress(PaymentSmoke):
    def prepare(self, user, quantity=1):
        draft = super().prepare(user,quantity)
        # Respect the production cap: release the consumed preparation delegation.
        self.request("DELETE","/api/auth/order-agent-token",user)
        return draft

    def snapshot(self):
        rows = query(self.conn,"SELECT balance,points FROM users WHERE user_id IN (%s,%s) ORDER BY user_id",tuple(self.names))
        return sum((r[0] for r in rows),Decimal(0)),sum(r[1] for r in rows),query(self.conn,"SELECT stock FROM medicines WHERE id=%s",(self.product,))[0][0]

    def parallel(self, jobs):
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            return [future.result() for future in [pool.submit(job) for job in jobs]]

    def post(self, token, order, action, grant=None, key=None):
        headers={"Authorization":"Bearer "+token}
        if action=="pay": headers.update({"X-Payment-Authorization":grant["token"],"Idempotency-Key":key or str(uuid.uuid4())})
        return self.http.post(self.base+f"/api/orders/{order}/{action}",json={"expectedVersion":1},headers=headers)

    def run(self):
        guard()
        tokens=[]
        for name,card in zip(self.names,[self.card,self.card_b]):
            self.request("POST","/api/auth/register",data={"userId":name,"password":self.password})
            token=self.request("POST","/api/auth/login",data={"userId":name,"password":self.password})["token"]
            tokens.append(token)
            self.request("POST","/api/auth/activate-wallet",token,{"password":self.pin})
            query(self.conn,"INSERT INTO recharge_cards(id,amount,is_used) VALUES (%s,50,0)",(card,))
            self.request("POST","/api/wallet/recharge",token,{"cardId":card})
        a,b=tokens
        with self.conn.cursor() as cursor:
            cursor.execute("INSERT INTO medicines(name,price,stock) VALUES (%s,1.10,1000)",(self.product_name,))
            self.product=cursor.lastrowid
        self.persist_fixture(); self.qualify_fixture()
        for round_id in range(5):
            oid=self.checkout(a,quantity=3)["orderId"]; cap=self.grant(a,oid); before=self.snapshot()
            keys=[f"shared-stress-{round_id}"]*5+[str(uuid.uuid4()) for _ in range(5)]
            replies=self.parallel([lambda key=key:self.post(a,oid,"pay",cap,key) for key in keys])
            after=self.snapshot()
            check(all(r.status_code==200 for r in replies),"Concurrent replay failed")
            check(len({r.json()["paymentId"] for r in replies})==1,"Concurrent payments differ")
            check(before[0]-after[0]==Decimal("3.30") and after[1]-before[1]==3 and before[2]-after[2]==3,"Duplicate financial write")
            check(query(self.conn,"SELECT COUNT(*) FROM transactions WHERE related_id=%s AND type='purchase'",(oid,))[0][0]==1,"Duplicate ledger")
            self.record("10 concurrent same/different-key requests debit and award points once",round=round_id+1)
        for round_id in range(5):
            first,second=self.checkout(a)["orderId"],self.checkout(b)["orderId"]
            ga,gb=self.grant(a,first),self.grant(b,second)
            prior_stock=self.snapshot()[2]
            query(self.conn,"UPDATE medicines SET stock=1 WHERE id=%s",(self.product,))
            before=self.snapshot()
            replies=self.parallel([lambda:self.post(a,first,"pay",ga),lambda:self.post(b,second,"pay",gb)])
            after=self.snapshot()
            check(sorted(r.status_code for r in replies)==[200,409],"Last stock did not have one winner")
            check(before[0]-after[0]==Decimal("1.10") and after[1]-before[1]==1 and after[2]==0,"Last-stock accounting mismatch")
            query(self.conn,"UPDATE medicines SET stock=%s WHERE id=%s",(prior_stock-1,self.product))
            self.record("Two users compete for last item without oversell or loser debit",round=round_id+1)
        for round_id in range(5):
            oid=self.checkout(a)["orderId"]; cap=self.grant(a,oid); before=self.snapshot()
            replies=self.parallel([lambda:self.post(a,oid,"pay",cap),lambda:self.post(a,oid,"close")])
            after=self.snapshot()
            check(sorted(r.status_code for r in replies)==[200,409],"Pay/close had multiple winners")
            status=query(self.conn,"SELECT payment_status FROM orders WHERE id=%s",(oid,))[0][0]
            paid=status=="PAID"
            check(before[0]-after[0]==(Decimal("1.10") if paid else Decimal(0)) and after[1]-before[1]==int(paid) and before[2]-after[2]==int(paid),"Terminal state accounting mismatch")
            self.record("Pay/close race has one terminal state and matching financial effects",round=round_id+1,terminal=status)
        scenarios=[("RX","sale_classification='RX'"), ("UNKNOWN","sale_classification='UNKNOWN'"),
            ("PENDING","review_status='PENDING'"),("qualification","qualification_version=2"),("price","price=1.11"),("stock","stock=0"),("balance",None)]
        for name,mutation in scenarios:
            oid=self.checkout(a)["orderId"]; cap=self.grant(a,oid); before=self.snapshot()
            own_balance=query(self.conn,"SELECT balance FROM users WHERE user_id=%s",(self.names[0],))[0][0]
            if mutation: query(self.conn,"UPDATE medicines SET "+mutation+" WHERE id=%s",(self.product,))
            else: query(self.conn,"UPDATE users SET balance=0 WHERE user_id=%s",(self.names[0],))
            reply=self.post(a,oid,"pay",cap)
            check(reply.status_code==(422 if name=="balance" else 409),"Unsafe sale was not refused")
            check(query(self.conn,"SELECT COUNT(*) FROM payment_records WHERE order_id=%s",(oid,))[0][0]==0,"Refused request created payment")
            if name=="balance": query(self.conn,"UPDATE users SET balance=%s WHERE user_id=%s",(own_balance,self.names[0]))
            query(self.conn,"UPDATE medicines SET sale_classification='OTC',review_status='APPROVED',qualification_version=1,price=1.10,stock=%s WHERE id=%s",(before[2],self.product))
            check(self.snapshot()==before,"Refusal changed money, points or inventory")
            self.record("Unsafe or insufficient conditions refuse all financial effects",scenario=name)
        oid=self.checkout(a)["orderId"]
        statuses=[]
        for _ in range(6):
            reply=self.http.post(self.base+f"/api/orders/{oid}/payment-authorizations",json={"expectedVersion":1,"password":"000000"},headers={"Authorization":"Bearer "+a})
            statuses.append(reply.status_code)
        check(statuses==[401]*5+[429],"Real PIN lockout failed")
        self.request("GET",f"/api/orders/{oid}",a)
        self.record("Five wrong PIN attempts persist and lock without expiring USER session")
        funds,points,stock=self.snapshot()
        ledger=query(self.conn,"SELECT COALESCE(SUM(t.amount),0),COALESCE(SUM(t.points_change),0),COUNT(*) FROM transactions t JOIN users u ON u.id=t.user_id WHERE u.user_id IN (%s,%s) AND t.type='purchase'",tuple(self.names))[0]
        settled=query(self.conn,"SELECT COUNT(*),COALESCE(SUM(o.total_price),0) FROM orders o JOIN users u ON u.id=o.user_id WHERE u.user_id IN (%s,%s) AND o.payment_status='PAID'",tuple(self.names))[0]
        quantity=query(self.conn,"SELECT COALESCE(SUM(i.quantity),0) FROM order_items i JOIN orders o ON o.id=i.order_id JOIN users u ON u.id=o.user_id WHERE u.user_id IN (%s,%s) AND o.payment_status='PAID'",tuple(self.names))[0][0]
        records=query(self.conn,"SELECT COUNT(*) FROM payment_records p JOIN users u ON u.id=p.user_id WHERE u.user_id IN (%s,%s)",tuple(self.names))[0][0]
        check(funds==Decimal(100)+ledger[0] and points==ledger[1] and stock==1000-quantity and settled[0]==ledger[2]==records and settled[1]==-ledger[0],"End-to-end financial reconciliation failed")
        self.financial_audit={"passed":True,"purchaseAmount":str(settled[1]),"paidOrders":settled[0],"purchaseLedgers":ledger[2],"paymentRecords":records,"pointsAwarded":points,"inventoryDeducted":int(quantity),"walletBalance":str(funds)}
        self.record("All paid orders reconcile wallet, points, ledgers and inventory")


if __name__=="__main__":
    smoke=Stress(); failure=None
    try: smoke.run()
    except Exception as exc: failure=type(exc).__name__+": "+str(exc)
    finally:
        try: smoke.cleanup()
        except Exception as exc: failure=(failure or "")+" cleanup: "+type(exc).__name__
    report={"passed":failure is None,"checks":smoke.results,"count":len(smoke.results),"financialAudit":getattr(smoke,"financial_audit",None),"failure":failure,"realHTTP":True,"realMySQL":True,"syntheticOnly":True,"roundsPerConcurrencyCase":5}
    (RUN/"m51d-stress.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report)); raise SystemExit(1 if failure else 0)
