"""Create one fresh, unpaid fault-test order through the real Java APIs."""
import argparse
import json
import os
os.environ["DEEPSEEKDOC_DEMO"]="1"
from demo import guard
from local_stack import RUN,query,target_fingerprint
from m51_live_smoke import PaymentSmoke

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("name",choices=("abort","switch","late","unauthorized"))
    name=parser.parse_args().name
    values=guard()
    path=RUN/"m51c-browser.json"
    fixture=json.loads(path.read_text(encoding="utf-8"))
    if fixture["targetFingerprint"]!=target_fingerprint(values): raise RuntimeError("Fixture target changed")
    smoke=PaymentSmoke()
    try:
        owned=query(smoke.conn,"SELECT id FROM medicines WHERE id=%s AND reference_source=%s",(fixture["product"],"local://synthetic-tests/"+fixture["prefix"]))
        if len(owned)!=1: raise RuntimeError("Synthetic product identity changed")
        smoke.product=fixture["product"]
        token=smoke.request("POST","/api/auth/login",data=fixture["a"])["token"]
        order=smoke.checkout(token,quantity=1)["orderId"]
        smoke.request("DELETE","/api/auth/order-agent-token",token)
        smoke.request("POST","/api/auth/logout",token)
        fixture.setdefault("orders",{})["d_"+name]=order
        path.write_text(json.dumps(fixture),encoding="utf-8")
        print(json.dumps({"freshUnpaidOrder":True,"scenario":name,"syntheticOnly":True}))
    finally: smoke.http.close(); smoke.conn.close()
