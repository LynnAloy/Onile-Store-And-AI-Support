<script setup>
import { ref, onMounted, watch } from "vue"
import { ShoppingCart, Search } from "@element-plus/icons-vue"
import { ElMessage, ElForm } from "element-plus"
import { useRouter } from "vue-router"
import { useWalletStore } from "@/stores/walletStore"
import { useUserStore } from "@/stores/userStore"
import { useOrderStore } from "@/stores/orderStore"
import { useMedicineStore } from "@/stores/medicineStore"
import { paymentsEnabled } from "@/services/paymentClient.mjs"

const walletStore = useWalletStore()
const userStore = useUserStore()
const orderStore = useOrderStore()
const medicineStore = useMedicineStore()
const loading = ref(true)
const medicines = ref([])
const searchTerm = ref('')

// 添加表单引用和路由声明
const formRef = ref(null);
const router = useRouter();

watch(() => medicineStore.medicines, () => {
  medicineStore.tableRefreshKey; // 强制表格重新渲染
}, { deep: true });

onMounted(async () => {
  try {
    await walletStore.fetchWalletData(); // 加载钱包数据
    await medicineStore.fetchMedicines(); // 加载药品数据
  } catch (error) {
    ElMessage.error("加载药品数据失败 " + error.message)
  } finally {
    loading.value = false; // 加载完成
  }
})

watch(searchTerm, (val) => {
  const kw = val.trim()
  medicineStore.fetchMedicines(kw)
}, { immediate: true })

const submitOrder = async () => {
  try {
    await formRef.value.validate();//where is Vakidate?
    await orderStore.submitOrder();//check
  } catch (error) {
    const errorMessage = error?.message || '订单提交失败，请重试';
    console.error("订单提交失败:", error);
    ElMessage.error(errorMessage);
  }
}
</script>

<template>
  <div class="order-container" :class="{ 'payment-catalog': paymentsEnabled }">
    <el-row :gutter="20">
      <!-- 药品列表 -->
      <el-col :span="16">
        <el-card class="medicine-list" shadow="hover">
          <el-input v-model="searchTerm" placeholder="搜索药品名称" :prefix-icon="Search" class="search-input" />
          <el-table :data="medicineStore.medicines" style="width: 100%" height="100%"
            :key="medicineStore.tableRefreshKey">
            <el-table-column prop="name" label="药品名称" />
            <el-table-column prop="price" label="单价（元）" />
            <el-table-column prop="tempStock" label="库存" />
            <el-table-column label="操作">
              <template #default="{ row }">
                <p v-if="!row.draftEligible">{{ row.draftBlockedReason || '商品资格待审核' }}</p>
                <el-button v-if="paymentsEnabled" type="primary" plain size="small" :disabled="!row.draftEligible" @click="router.push('/main')">去对话核对清单</el-button>
                <el-button v-else type="primary" size="small" :disabled="!row.draftEligible" @click="orderStore.addToCart(row)">
                  加入购物车
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>

      <!-- 购物车和订单 -->
      <el-col :span="8">
        <el-card v-if="paymentsEnabled" shadow="never" class="new-checkout-note">
          <h3>独立付款流程</h3><p>在对话中选择商品与数量，授权准备草稿；核对收货资料后，进入独立付款页面验证并明确付款。</p>
          <p>准备、确认资料和验证密码均不扣款。</p>
          <RouterLink to="/main"><el-button type="primary" plain>去对话准备草稿</el-button></RouterLink>
          <RouterLink to="/drafts"><el-button plain>我的草稿</el-button></RouterLink>
          <RouterLink to="/payments"><el-button plain>付款订单</el-button></RouterLink>
        </el-card>
        <el-card v-else class="cart-section" shadow="hover">
          <h3 class="section-title">
            <ShoppingCart style="width: 1.2em; height: 1.2em" />
            购物车
          </h3>
          <el-divider />
          <div class="cartItemsContainer">
            <div v-for="item in orderStore.cart" :key="item.id" class="cart-item">
              <div class="item-info">
                <span class="name">{{ item.name }}</span>
                <span class="price">¥{{ item.price }}</span>
              </div>
              <div class="item-actions">
                <el-input-number  v-model="item.quantity" @change="(newQuantity, oldQuantity) => orderStore.updateItemQuantity(item, oldQuantity, newQuantity)" size="small" :min="1" :max="medicineStore.getMedicineById(item.id)?.stock" />
                <el-button class="deleteButton" type="danger" plain size="small"
                  @click="orderStore.removeFromCart(item)">
                  删除
                </el-button>
              </div>
            </div>
          </div>
          <el-form ref="formRef" :model="orderStore.orderForm" :rules="orderStore.infoRules" class="order-form">
            <el-form-item label="收货人" prop="recipientName">
              <el-input v-model="orderStore.orderForm.recipientName" placeholder="请输入收货人姓名" />
            </el-form-item>

            <el-form-item label="联系电话" prop="recipientPhone">
              <el-input v-model="orderStore.orderForm.recipientPhone" placeholder="请输入联系电话" />
            </el-form-item>

            <el-form-item label="收货地址" prop="recipientAddress">
              <el-input v-model="orderStore.orderForm.recipientAddress" placeholder="请输入收货地址" />
            </el-form-item>

            <el-form-item label="备注" prop="note">
              <el-input v-model="orderStore.orderForm.note" type="textarea" :rows="2" />
            </el-form-item>

            <el-button type="primary" class="submit-btn" @click="submitOrder"
              :disabled="!orderStore.cart || orderStore.cart.length === 0">
              立即下单(¥{{ orderStore.totalPrice.toFixed(2) }})
            </el-button>
          </el-form>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.new-checkout-note { border-radius: 6px; font-size: 13px; line-height: 1.8; }
.new-checkout-note p { color: #909399; }
.new-checkout-note a { display: block; margin-top: 12px; }
@media(max-width: 760px) {
  .payment-catalog :deep(.el-col) { flex: 0 0 100%; max-width: 100%; margin-bottom: 14px; }
  .payment-catalog .medicine-list { height: 420px; border-radius: 6px; }
}
.order-container {
  max-width: 1200px;
  margin: 5px 10px;
}

.medicine-list {
  border-radius: 12px;
  background: #f8f9fa;
  height: calc(100vh - 100px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.search-input {
  margin-bottom: 20px;
  flex-shrink: 0;
}

.cart-section {
  height: calc(100vh - 100px);
  /* 与左侧等高 */
  background: #fff;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  /* 防止外层滚动 */
}

.section-title {
  color: #409EFF;
  display: flex;
  align-items: center;
  gap: 8px;
  margin: -10px 0 -20px 0;
}

.cartItemsContainer {
  flex: 1;
  overflow-y: auto;
  margin-bottom: 15px;
  border: 1px solid #eee;
  border-radius: 8px;
  padding: 10px;
}

.cart-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 0;
  border-bottom: 1px solid #eee;
}

:deep(.deleteButton) {
  margin-left: 10px;
}

.cart-item:last-child {
  border-bottom: none;
}

.item-info {
  display: flex;
  flex-direction: column;
}

.name {
  font-weight: 500;
}

.price {
  color: #f56c6c;
  font-size: 0.9em;
}

.order-form {
  flex-shrink: 0;
}

.submit-btn {
  width: 100%;
  margin-top: 20px;
}

:deep(.el-table) {
  --el-table-border-color: transparent;
  --el-table-header-bg-color: #f8f9fa;
  flex: 1;
  overflow: hidden;
}

:deep(.el-table__body-wrapper) {
  overflow-y: auto !important;
  height: calc(100% - 55px);
}

:deep(.el-table__body) {
  height: 100%;
}

:deep(.el-card__body) {
  padding: 20px;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.search-input {
  margin-bottom: 20px;
  flex-shrink: 0;
}
</style>
