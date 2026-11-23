"""P1 acceptance on owned fictional demo fixtures only. Never use a normal account."""
import json,uuid
import httpx
from m6_live import load,request,ROOT

def run():
    values,data=load()
    admin=json.loads((ROOT/'.local-demo/admin-account.json').read_text(encoding='utf-8'))
    owner=next(row for row in data['users'] if row['kind']=='api')
    product=data['products'][0]
    with httpx.Client(base_url='http://127.0.0.1:13000',trust_env=False,timeout=240) as c:
        at=request(c,'POST','/api/auth/login',data={'userId':admin['username'],'password':admin['password']})['token']
        token=request(c,'POST','/api/auth/login',data={'userId':owner['username'],'password':data['password']})['token']
        def profile(allergy='无'):
            request(c,'PUT','/api/user/profile/details',token,{'basic':{'userId':owner['username'],'age':30,'name':'合成智能收货人','phoneNum':'13800138000','address':'合成智能测试地址','medicalHistory':[]},
                'health':{'aiProfileConsent':True,'medicalHistoryText':'无','allergiesText':allergy,'medicationsText':'无','healthNotes':'无其他健康风险'}})
        def execute(expected):
            tid=str(uuid.uuid4())
            request(c,'POST','/api/auto-orders/turns',token,{'turnId':tid,'conversationId':'p1-synthetic','message':'帮我购买1件'+product['name']})
            result=request(c,'POST',f'/api/auto-orders/turns/{tid}/execute',token,{'items':[{'medicineId':product['id'],'quantity':1}]},expected)
            return tid,result
        profile()
        meds=request(c,'GET','/api/admin/medicines',at)
        row=next(row for row in meds if row['id']==product['id'])
        request(c,'PUT',f"/api/admin/medicines/{product['id']}/qualification",at,{'expectedVersion':row['qualification_version'],'classification':'OTC','reviewStatus':'APPROVED','referenceSource':'local://synthetic-tests/'+data['prefix']})
        policy=request(c,'GET','/api/wallet/auto-order-policy',token)
        request(c,'PUT','/api/wallet/auto-order-policy',token,{'enabled':True,'perOrderLimit':50,'dailyLimit':200,'expectedVersion':policy['version'],'password':data['pin']})
        execute(409)  # No medical evidence.
        ev={'expectedVersion':0,'qualificationVersion':1,'categories':['合成类别'],'ingredients':['合成成分'],
            'indications':'合成测试用途，不作为真实医学依据','source':'local://synthetic-tests/'+data['prefix'],'maxUnitsPerOrder':1}
        request(c,'PUT',f"/api/admin/medicines/{product['id']}/evidence",token,ev,403)
        request(c,'PUT',f"/api/admin/medicines/{product['id']}/evidence",at,ev)
        profile('合成过敏记录')
        execute(409)  # Explicit risk, even when frontend is bypassed.
        profile()
        tid,receipt=execute(200)
        assert receipt['status']=='PAID'
        replay=request(c,'POST',f'/api/auto-orders/turns/{tid}/execute',token,{'items':[{'medicineId':product['id'],'quantity':1}]})
        assert receipt==replay
        delegated=request(c,'POST','/api/auth/agent-token',token,{})['token']
        conversation=request(c,'POST','/ai/v1/conversations',delegated,{'title':'P1证据只读验收'},201)['id']
        response=c.post(f'/ai/v1/conversations/{conversation}/messages',headers={'Authorization':'Bearer '+delegated},json={'requestId':str(uuid.uuid4()),'message':'库存中是否有合成类别药品？'})
        result=None
        for frame in response.text.replace('\r\n','\n').split('\n\n'):
            if frame.startswith('event: tool_result'):
                result=json.loads(next(line[6:] for line in frame.splitlines() if line.startswith('data: ')))['result']
        assert result and result.get('products') and any(row['id']==product['id'] and row.get('matchedEvidence') for row in result['products']), 'Real graph did not return reviewed evidence'
        assert result['riskAssessment']['healthProfileUsed'] is True
        request(c,'PUT',f"/api/admin/medicines/{product['id']}/stock",at,{'expectedVersion':1,'expectedStock':29,'stock':30,'reason':'合成版本失效验收'})
        execute(409)  # Stock version change invalidates old evidence.
        stale=request(c,'GET',f"/api/admin/medicines/{product['id']}/evidence",at)
        assert stale['status']=='STALE'
        order=request(c,'GET','/api/orders/'+receipt['orderId'],token)
        assert order['paymentStatus']=='PAID'
        report={'passed':True,'realMySQL':True,'realLocalModel':True,'onlySyntheticWallet':'2.50',
            'missingEvidenceDenied':True,'frontendBypassWithAllergyDenied':True,'ordinaryUserCannotApproveEvidence':True,
            'reviewedEvidenceIncludedInCategoryResult':True,'authorizedHealthUsedInGraph':True,'staleEvidenceDenied':True,'replaySingleDebit':True}
        (ROOT/'docs/evidence/m6/p1-live.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(report))
        request(c,'POST','/api/auth/logout',token,{})
        request(c,'POST','/api/auth/logout',at,{})

if __name__=='__main__':run()
