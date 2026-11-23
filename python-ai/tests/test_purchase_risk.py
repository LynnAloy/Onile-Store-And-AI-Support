import unittest
from app.purchase_risk import assess
class PurchaseRiskTests(unittest.TestCase):
    def test_consent_missing_or_health_risk_never_allows_automatic_order(self):
        self.assertFalse(assess({})["automaticPurchaseAllowed"])
        base={"healthNotes":"无其他健康风险","age":30,"medicalHistoryText":"无","allergiesText":"无","medicationsText":"无"}
        self.assertTrue(assess({"userReportedHealth":base})["automaticPurchaseAllowed"])
        for key,value in (("age",17),("age",70),("allergiesText","布洛芬过敏"),("medicationsText","正在用药"),("healthNotes","孕期")):
            self.assertFalse(assess({"userReportedHealth":{**base,key:value}})["automaticPurchaseAllowed"])
        self.assertFalse(assess({"userReportedHealth":base,"omittedHealthFields":["medicalHistory"]})["automaticPurchaseAllowed"])
