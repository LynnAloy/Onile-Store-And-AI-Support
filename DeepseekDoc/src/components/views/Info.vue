<script setup>
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { MedicalOptions } from "@/assets/data/MedicalOptions.js";
import { useUserStore } from "@/stores/userStore";
import { useWalletStore } from "@/stores/walletStore";
import { useOrderStore } from "@/stores/orderStore";
import { ElMessage } from "element-plus";
import { paymentsEnabled, paymentStatusLabel } from "@/services/paymentClient.mjs";

const router = useRouter();
const userStore = useUserStore();
const walletStore = useWalletStore();
const orderStore = useOrderStore();
const formRef = ref(null);
const saving = ref(false);
const loading = ref(true);
const orderPhone = ref("");
const formModel = computed(() => ({ ...userStore.userInfo, ...userStore.healthProfile }));
const savedConsent = ref(false);
const rules = {
  nickname: [{ required: true, min: 2, max: 50, message: "昵称需为2-50个字符", trigger: "blur" }],
  email: [{ type: "email", message: "请输入有效邮箱地址", trigger: "blur" }],
  age: [{ type: "number", min: 0, max: 120, message: "年龄应在0-120岁之间", trigger: "blur" }],
};
const bmi = computed(() => {
  const { heightCm, weightKg } = userStore.healthProfile;
  return heightCm && weightKg ? (weightKg / ((heightCm / 100) ** 2)).toFixed(1) : "";
});

onMounted(async () => {
  try {
    await userStore.fetchUserProfile();
    savedConsent.value = userStore.healthProfile.aiProfileConsent;
    if (userStore.isHealthWalletActive) {
      await walletStore.fetchWalletData();
      await orderStore.searchOrders();
    }
  } catch {
    ElMessage.error("个人中心数据加载失败，请刷新后重试");
  } finally {
    loading.value = false;
  }
});

async function saveProfile() {
  if (saving.value) return;
  try {
    if (!(await formRef.value.validate().catch(() => false))) return;
    saving.value = true;
    const saved = await userStore.updateUserProfile();
    if (saved) savedConsent.value = userStore.healthProfile.aiProfileConsent;
  } finally {
    saving.value = false;
  }
}

const searchOrders = () => orderStore.searchOrders(orderPhone.value.trim());
</script>

<template>
  <main v-loading="loading" class="profile-container">
    <section class="profile-main">
      <el-card>
        <template #header><h2>个人资料与健康档案</h2></template>
        <p class="hint">健康资料由你自主填写；留空表示未提供，不代表不存在相应情况。</p>
        <el-form ref="formRef" :model="formModel" :rules="rules" label-position="top">
          <div class="form-grid">
            <el-form-item label="昵称" prop="nickname">
              <el-input v-model="userStore.userInfo.nickname" maxlength="50" />
            </el-form-item>
            <el-form-item label="邮箱" prop="email">
              <el-input v-model="userStore.userInfo.email" maxlength="100" />
            </el-form-item>
            <el-form-item label="姓名">
              <el-input v-model="userStore.healthProfile.name" maxlength="15" />
            </el-form-item>
            <el-form-item label="年龄（岁）" prop="age">
              <el-input-number v-model="userStore.healthProfile.age" :min="0" :max="120" :precision="0" />
            </el-form-item>
            <el-form-item label="性别（可不填）">
              <el-select v-model="userStore.healthProfile.gender" clearable>
                <el-option label="男" value="Male" />
                <el-option label="女" value="Female" />
              </el-select>
            </el-form-item>
            <el-form-item label="生日">
              <el-date-picker v-model="userStore.healthProfile.birthday" type="date"
                value-format="YYYY-MM-DD" placeholder="选择日期" />
            </el-form-item>
            <el-form-item label="手机号">
              <el-input v-model="userStore.healthProfile.phoneNum" maxlength="20" />
            </el-form-item>
            <el-form-item label="住址">
              <el-input v-model="userStore.healthProfile.address" maxlength="50" />
            </el-form-item>
            <el-form-item label="身高（cm）">
              <el-input-number v-model="userStore.healthProfile.heightCm" :min="30" :max="260"
                :precision="1" :step="0.1" />
            </el-form-item>
            <el-form-item label="体重（kg）">
              <el-input-number v-model="userStore.healthProfile.weightKg" :min="1" :max="500"
                :precision="1" :step="0.1" />
            </el-form-item>
          </div>
          <p v-if="bmi" class="hint">BMI 计算值：{{ bmi }}。这里只展示数值，不作诊断或用药判断。</p>
          <el-form-item label="既往病史标签（支持自行输入）">
            <el-select v-model="userStore.healthProfile.medical" multiple filterable allow-create
              default-first-option :multiple-limit="30" placeholder="选择或输入病史标签">
              <el-option v-for="item in MedicalOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="既往病史详细描述">
            <el-input v-model="userStore.healthProfile.medicalHistoryText" type="textarea" :rows="4"
              maxlength="2000" show-word-limit placeholder="可自主描述既往疾病、手术、发生时间等；无需填写账号密码或身份编号。" />
          </el-form-item>
          <div class="form-grid">
            <el-form-item label="过敏情况">
              <el-input v-model="userStore.healthProfile.allergiesText" type="textarea" :rows="3"
                maxlength="1000" show-word-limit placeholder="已知药物、食物过敏及反应；不确定时可写明。" />
            </el-form-item>
            <el-form-item label="正在使用的药物或补充剂">
              <el-input v-model="userStore.healthProfile.medicationsText" type="textarea" :rows="3"
                maxlength="1000" show-word-limit />
            </el-form-item>
          </div>
          <el-form-item label="生活习惯">
            <el-input v-model="userStore.healthProfile.lifestyleText" type="textarea" :rows="3"
              maxlength="1000" show-word-limit placeholder="可填写运动、睡眠、饮食等情况。" />
          </el-form-item>
          <el-form-item label="其他健康说明">
            <el-input v-model="userStore.healthProfile.healthNotes" type="textarea" :rows="3"
              maxlength="2000" show-word-limit placeholder="可填写希望补充的情况；健康资料均为自述信息。" />
          </el-form-item>
          <section class="consent-panel">
            <el-checkbox v-model="userStore.healthProfile.aiProfileConsent" data-testid="profile-consent">
              同意使用健康档案提供个性化建议，并在我的订单草稿中预填收货资料
            </el-checkbox>
            <p>默认关闭，不影响普通对话。模型仅接收年龄、性别、身高体重与上述健康描述。
              姓名、手机号和住址由订单服务预填，供你在确认草稿前核对。个人档案不写入公共知识库。</p>
            <p>修改或取消需点击保存后生效。已发送给模型的资料无法追回，历史聊天不会自动删除；
              取消后停止自动注入档案和预填收货资料，也不再把旧个性化回答用于后续上下文。
              你主动输入聊天的信息仍用于对话。</p>
            <el-tag :type="savedConsent ? 'success' : 'info'">
              服务端已保存：{{ savedConsent ? '已授权个性化' : '未授权个性化' }}
            </el-tag>
            <span v-if="savedConsent !== userStore.healthProfile.aiProfileConsent" class="unsaved">
              授权选择尚未保存
            </span>
          </section>
          <el-button type="primary" :loading="saving" @click="saveProfile">保存资料与授权选择</el-button>
        </el-form>
      </el-card>
    </section>
    <aside>
      <el-card>
        <template #header><h3>健康钱包</h3></template>
        <p>余额：¥{{ Number(walletStore.balance || 0).toFixed(2) }}</p>
        <p>积分：{{ walletStore.points }}</p>
        <el-button @click="router.push(userStore.isHealthWalletActive ? '/charge' : '/activate')">
          {{ userStore.isHealthWalletActive ? '充值' : '开通钱包' }}
        </el-button>
      </el-card>
      <el-card class="orders">
        <template #header><h3>我的订单</h3></template>
        <p v-if="paymentsEnabled"><RouterLink to="/payments">查看付款订单与恢复付款结果</RouterLink></p>
        <el-input v-model="orderPhone" placeholder="按收货手机号查询本人订单" clearable @keyup.enter="searchOrders" />
        <el-button class="search" @click="searchOrders">查询</el-button>
        <el-empty v-if="!orderStore.orders.length" description="暂无订单" />
        <article v-for="order in orderStore.orders" :key="order.id">
          <p>{{ order.id }} · {{ order.paymentStatus ? paymentStatusLabel(order.paymentStatus) : order.status }}</p>
          <p v-for="item in order.items" :key="item.medicineId || item.id">{{ item.name || '历史商品' }} × {{ item.quantity }}</p>
          <RouterLink v-if="paymentsEnabled && order.paymentStatus" :to="`/payment/${encodeURIComponent(order.id)}`">查看付款详情</RouterLink>
        </article>
      </el-card>
    </aside>
  </main>
</template>

<style scoped>
.profile-container { display: grid; grid-template-columns: minmax(0, 2fr) minmax(260px, 1fr); gap: 20px; max-width: 1250px; margin: 20px auto; padding: 0 16px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 20px; }
h2, h3 { margin: 0; }
.hint { color: #606266; font-size: 14px; line-height: 1.7; }
.consent-panel { margin: 20px 0; padding: 18px; border: 1px solid #c6e2ff; border-radius: 10px; background: #f5f9ff; }
.consent-panel p { font-size: 13px; line-height: 1.8; color: #606266; }
:deep(.el-checkbox) { height: auto; white-space: normal; align-items: flex-start; }
:deep(.el-checkbox__label) { white-space: normal; line-height: 1.7; }
:deep(.el-input-number), :deep(.el-date-editor), :deep(.el-select) { width: 100%; }
.unsaved { margin-left: 12px; color: #a35c00; font-size: 13px; }
.orders { margin-top: 20px; }
.search { margin: 10px 0; }
article { border-top: 1px solid #ebeef5; padding: 12px 0; font-size: 13px; overflow-wrap: anywhere; }
@media (max-width: 850px) { .profile-container { grid-template-columns: 1fr; } }
@media (max-width: 520px) { .form-grid { grid-template-columns: 1fr; } }
</style>
