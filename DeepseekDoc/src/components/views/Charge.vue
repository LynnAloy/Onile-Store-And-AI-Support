<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from "element-plus"
import { useWalletStore } from '@/stores/walletStore'
import { useUserStore } from '@/stores/userStore'
import AutoOrderPolicy from './AutoOrderPolicy.vue'
import { commerceEnabled } from '@/services/commerceClient.mjs'

const walletStore = useWalletStore()
const userStore = useUserStore()
const cardKey = ref('')
const exchangePoints = ref(0)
const generatedKey = ref('')
const isLoading = ref(false)

onMounted(async () => {
  isLoading.value = true
  try {
    await walletStore.fetchWalletData()
  } catch (error) {
    ElMessage.error('获取钱包数据失败: ' + error.message)
  } finally {
    isLoading.value = false
  }
})


// 充值卡验证
const recharge = async () => {
  if (!cardKey.value) {
    ElMessage.warning('请输入充值卡密');
    return;
  }
  isLoading.value = true
  const formatedCardKey = cardKey.value.trim();
  try {
    await walletStore.recharge(userStore.userId, formatedCardKey)
    cardKey.value = ''
    ElMessage.success('充值成功！');
  } catch (error) {
    ElMessage.error(`充值失败：${error.message || '未知错误'}`);
  } finally {
    isLoading.value = false
  }
}

// 积分兑换
const exchange = async() => {
  const currentPoints = walletStore.points || 0;

  if (exchangePoints.value > currentPoints) {
    ElMessage.warning('积分不足')
    return
  }

  try {
    isLoading.value = true;
    await walletStore.exchangePoints(userStore.userId, exchangePoints.value);
    ElMessage.success(`成功兑换${exchangePoints.value}积分！`);
    exchangePoints.value = 0;
  } catch (error) {
  } finally {
    isLoading.value = false;
  }
}
</script>

<template>
  <div class="charge-container">
    <el-card class="wallet-card" shadow="hover">
      <!-- 账户概览 -->
      <div class="wallet-overview">
        <h2>账户概览</h2>
        <div class="balance-container">
          <div class="amount-card money">
            <div class="amount">￥{{ Number(walletStore.balance || 0).toFixed(2) }}</div>
            <div class="label">可用余额</div>
          </div>
          <div class="amount-card point">
            <div class="amount">{{ Number(walletStore.points || 0) }}</div>
            <div class="label">健康积分</div>
          </div>
        </div>
      </div>

      <AutoOrderPolicy v-if="commerceEnabled" />
      <!-- 充值卡充值 -->
      <div class="recharge-section">
        <h3>卡密充值</h3>
        <el-input v-model="cardKey" placeholder="请输入充值卡密（示例：DEEPS-12345）" style="width: 300px; margin-right: 15px" />
        <el-button type="primary" plain :plain="true" @click="recharge">立即充值</el-button>
      </div>

      <!-- 积分兑换 -->
      <div class="exchange-section">
        <h3>积分兑换</h3>
        <div class="exchange-rules">
          <el-text type="info">兑换规则：每10积分可兑换1元余额</el-text>
        </div>
        <el-input-number v-model="exchangePoints" :min="10" :step="10" style="width: 200px; margin: 15px 0" />
        <el-button type="success" plain :plain="true" @click="exchange">确认兑换</el-button>

        <el-alert v-if="generatedKey" :title="`生成卡密：${generatedKey}`" type="info" show-icon style="margin-top: 15px" />
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.charge-container {
  max-width: 800px;
  margin: 5px 0px 10px 10px;
  padding: 0px;
}

:deep(.el-card.is-hover-shadow.wallet-card) {
  padding: 0px 25px 25px 25px;
}

:deep(.wallet-card .el-card__body) {
  padding: 0px !important;
}

.wallet-card {
  padding: 25px;
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
}

.wallet-overview h2,
.recharge-section h3,
.exchange-section h3 {
  color: #409EFF;
  margin-bottom: 15px;
}

.recharge-section,
.exchange-section {
  margin: 20px 0;
  padding: 20px 20px 20px 0px;
  background: #ffffff;
  border-radius: 8px;
}

.exchange-rules {
  margin: 10px 0;
}

:deep(.el-button.el-button--success) {
  margin: 0px 0px 0px 15px;
}

.balance-container {
  display: flex;
  gap: 20px;
  margin: 25px 0;
}

.amount-card {
  flex: 1;
  padding: 25px;
  border-radius: 12px;
  text-align: center;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
}

.amount {
  font-size: 32px;
  font-weight: 600;
  margin-bottom: 8px;
}

.label {
  font-size: 14px;
  color: #666;
}

.money {
  background: #b4daff;
  border: 1px solid #b7eb8f;
}

.point {
  background: #b4daff;
  border: 1px solid #ffe58f;
}
</style>
