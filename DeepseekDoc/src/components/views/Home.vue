<template>
  <section class="chat-wrapper" aria-label="家庭健康助手">
    <header class="chat-header">
      <div class="chat-title"><h2>家庭健康助手</h2><span>咨询 · 查询 · 核对清单</span></div>
      <div class="chat-toolbar">
        <el-select v-model="conversationId" class="conversation-select" aria-label="选择会话"
          placeholder="选择会话" :disabled="loading || loadingHistory || !userStore.isLoggedIn" @change="loadSelected">
          <el-option v-for="item in conversations" :key="item.id" :value="item.id"
            :label="item.title + ' · ' + new Date(item.createdAt * 1000).toLocaleDateString()" />
        </el-select>
        <el-button :icon="Plus" :disabled="loading || loadingHistory || !userStore.isLoggedIn" @click="newConversation">新对话</el-button>
        <el-button :icon="Refresh" circle aria-label="刷新记录" title="刷新记录"
          :disabled="loading || loadingHistory || !conversationId" @click="loadSelected" />
        <el-popover placement="bottom-end" :width="320" trigger="click">
          <template #reference><el-button :icon="InfoFilled" circle aria-label="使用说明" title="使用说明" /></template>
          <div class="help-content">
            <strong>使用说明</strong>
            <p>AI建议仅供参考，商品查询不代表适合用药。价格、库存和历史卡片均为查询快照。</p>
            <p>默认核对清单后手动下单。钱包开启“允许 AI 智能下单”后，明确商品和数量的本轮请求可自动购买审核通过的非处方商品并扣除演示余额。</p>
            <p>停止生成不保证撤销已保存的草稿，可到“我的草稿”核对。订单准备授权最长5分钟。</p>
            <RouterLink to="/drafts">查看我的草稿</RouterLink>
            <el-button link type="danger" :disabled="!userStore.isLoggedIn" @click="revokeOrderPreparation">撤销订单准备授权</el-button>
          </div>
        </el-popover>
      </div>
    </header>

    <div class="conversation-stage">
    <div ref="chatbox" class="chatbox" role="log" tabindex="0" aria-label="对话记录" aria-live="polite" :aria-busy="loading" @scroll="trackScroll">
      <el-alert v-if="errorText" :title="errorText" type="error" show-icon @close="errorText = ''" />
      <div v-if="!userStore.isLoggedIn || (!messages.length && !loadingHistory)" class="empty-state">
        <el-icon :size="42"><ChatDotRound /></el-icon>
        <h3>{{ userStore.isLoggedIn ? '有什么可以帮你？' : '欢迎使用家庭健康助手' }}</h3>
        <p>咨询健康问题、查询商品，或核对你的购买清单。</p>
        <RouterLink v-if="!userStore.isLoggedIn" to="/login" class="empty-login">登录后开始对话</RouterLink>
      </div>
      <p v-if="loadingHistory" class="loading-label"><el-icon class="is-loading"><Loading /></el-icon>正在加载会话…</p>
      <article v-for="(message, index) in messages" :key="index" :class="['message', message.sender]">
        <div class="message-heading"><el-icon><User v-if="message.sender === 'user'" /><ChatDotRound v-else /></el-icon>
          <span>{{ message.sender === 'user' ? '您' : 'AI 助手' }}</span>
        </div>
        <div v-if="message.content && message.autoResult?.status !== 'PAID'" class="message-content">{{ message.content }}</div>
        <article v-if="message.autoResult" class="business-result auto-result" aria-live="polite">
          <template v-if="message.autoResult.status === 'PAID'">
            <strong>智能下单已完成 · 演示钱包已扣款 ¥{{ message.autoResult.payment.amount }}</strong>
            <p>订单 {{ message.autoResult.orderId }}，收货资料已从个人资料填写。</p>
            <RouterLink :to="'/payment/' + message.autoResult.orderId">查看订单与扣款记录</RouterLink>
          </template>
          <p v-else>{{ message.autoResult.message || (message.autoResult.status === 'REJECTED' ? '本轮自动下单未执行：' + message.autoResult.code : '本轮下单结果需要核对') }}</p>
          <el-button v-if="message.autoResult.status === 'UNKNOWN'" link type="primary" @click="checkAutoResult(message)">查询本轮结果</el-button>
        </article>

        <details v-for="tool in toolRows(message.toolEvents)" :key="tool.callId" class="tool-card" :open="toolExpanded(tool, message)">
          <summary><span>{{ toolLabel(tool.tool) }}</span><span :class="['tool-status', tool.status]">{{ toolState(tool, message) }}</span></summary>
          <div class="tool-body">
            <div v-if="tool.result?.catalogListing" class="muted">
              库存列表 · 已读取 {{ tool.result.catalogCount }} 项{{ tool.result.catalogTruncated ? ' · 目录未全部覆盖' : '' }}
            </div>
            <div v-else-if="tool.result?.plan" class="muted"><p>任务：{{ tool.result.plan.intent === 'purchase' ? '购买清单核对' : '库存语义检索' }} · 关键词：{{ tool.result.plan.keywords.join('、') }}</p><p>已检查 {{ tool.result.catalogCount }} 项库存 · {{ tool.result.catalogTruncated ? '目录未全部覆盖' : '本轮目录已读取' }}</p></div>
            <p v-if="tool.result?.ok === false" class="blocked-text">{{ tool.result.message }}</p>
            <p v-if="tool.result?.riskAssessment" class="muted">健康资料风险复核：{{ tool.result.riskAssessment.automaticPurchaseAllowed ? '未发现已填资料触发的自动化阻断' : '需人工核对，不自动扣款' }}。{{ tool.result.riskAssessment.notice }}</p>
            <p v-if="tool.result?.evidenceRequired" class="muted">尚无足够的有效审核证据确认此类别，不等于库存没有相关商品。</p>
            <p v-if="tool.result?.ok && tool.result.products?.length === 0" class="muted">没有找到匹配商品。</p>
            <div v-if="tool.result?.analysis">
              <p class="muted">模型按药品常见用途匹配，个人用药需另行核对。</p>
              <article v-for="item in tool.result.analysis.items" :key="item.medicineId" class="product-row">
                <div class="product-heading"><strong>{{ item.name }}</strong><span class="price">¥{{ item.price }}</span></div>
                <div class="product-meta">商品 {{ item.medicineId }} · 库存 {{ item.stock }}</div>
                <p>{{ item.matchesNeed === null ? '未判断' : item.matchesNeed ? '符合需求' : '未匹配需求' }}</p>
              </article>
            </div>
            <p v-if="tool.result?.requiresProductChoice" class="muted">请核对规格和数量，选入清单后授权准备未付款草稿。</p>
            <article v-for="product in tool.result?.products || []" :key="product.id" class="product-row">
              <div class="product-heading"><strong>{{ product.name }}</strong><span class="price">¥{{ product.price }}</span></div>
              <div class="product-meta">商品 {{ product.id }} · 库存 {{ product.stock }}</div>
              <p v-if="product.matchedEvidence" class="muted">审核类别：{{ product.matchedEvidence.categories.join('、') }} · 证据版本 {{ product.matchedEvidence.version }} · {{ product.matchedEvidence.source }}</p>
              <p v-if="!product.draftEligible" class="blocked-text">{{ product.draftBlockedReason || '商品资格待核验' }}</p>
              <div class="product-controls">
                <el-input-number v-model="draftQuantities[product.id]" :min="1" :max="99" :precision="0" size="small"
                  controls-position="right" placeholder="数量" :aria-label="product.name + '的数量'" :disabled="authorizing || message.autoResult?.status === 'PAID'" />
                <el-checkbox :model-value="draftSelection.some(item => item.id === product.id)"
                  :disabled="!canSelectProduct(product, draftSelection, loading || loadingHistory || authorizing || message.autoResult?.status === 'PAID')"
                  @change="checked => toggleDraftSelection(product, checked)">选入清单</el-checkbox>
              </div>
            </article>

            <div v-if="tool.result?.proposal" class="proposal">
              <p class="muted">{{ message.autoResult?.status === 'PAID' ? '本轮清单已智能下单，付款状态以上方订单回执为准。' : '已保留请求数量，请核对商品；此卡片为清单快照。' }}</p>
              <article v-for="item in tool.result.proposal.items" :key="item.id" class="product-row">
                <div class="product-heading"><strong>{{ item.name }}</strong><span class="product-meta">请求 {{ item.quantity ?? '待填' }} 件</span></div>
                <p v-if="!item.draftEligible" class="blocked-text">{{ item.draftBlockedReason }}</p>
                <p v-if="item.selectionNote" class="blocked-text">{{ item.selectionNote }}</p>
                <div class="product-controls">
                  <el-input-number v-model="draftQuantities[item.id]" :min="1" :max="99" :precision="0" size="small"
                    controls-position="right" placeholder="数量" :aria-label="item.name + '的数量'" :disabled="authorizing || message.autoResult?.status === 'PAID'" />
                  <el-checkbox :model-value="draftSelection.some(product => product.id === item.id)"
                    :disabled="!canSelectProduct(item, draftSelection, loading || loadingHistory || authorizing || message.autoResult?.status === 'PAID')"
                    @change="checked => toggleDraftSelection(item, checked)">选入清单</el-checkbox>
                </div>
              </article>
              <el-button link type="primary" :disabled="loading || authorizing || message.autoResult?.status === 'PAID'" @click="useProposal(tool.result.proposal)">载入这份清单</el-button>
            </div>

            <article v-if="tool.result?.order" class="business-result">
              <p>订单 {{ tool.result.order.orderId }} · {{ tool.result.order.status }}</p>
              <p class="price">¥{{ tool.result.order.totalPrice }}</p>
              <p v-for="(item, itemIndex) in tool.result.order.items" :key="itemIndex">{{ item.name }} × {{ item.quantity }} · 单价 ¥{{ item.price }}</p>
            </article>
            <article v-if="tool.result?.draft" class="business-result">
              <div class="product-heading"><strong>未付款草稿</strong><span class="price">¥{{ tool.result.draft.totalPrice }}</span></div>
              <p v-for="item in tool.result.draft.items" :key="item.medicineId">{{ item.name }} × {{ item.quantity }}</p>
              <p class="muted">不扣款、不占用库存</p>
              <RouterLink :to="{ path: '/drafts', query: { id: tool.result.draft.draftId } }">核对草稿与当前状态</RouterLink>
            </article>
            <small v-if="tool.result?.queriedAt" class="snapshot-note">查询快照 · {{ new Date(tool.result.queriedAt).toLocaleString() }}</small>
          </div>
        </details>

        <div v-if="message.sender === 'bot'" class="message-meta">
          <span v-if="message.status && message.status !== 'completed'">{{ statusLabel(message.status) }}</span>
          <span v-if="message.personalizationApplied !== undefined">{{ message.personalizationApplied ? '已授权个性化' : '未自动使用健康档案' }}</span>
          <span v-if="message.retrieval && !message.citations?.length">未引用知识资料</span>
        </div>
        <details v-if="message.citations?.length" class="sources">
          <summary>参考资料 · {{ message.citations.length }}</summary>
          <article v-for="source in message.citations" :key="source.chunkId">
            <strong>[{{ source.id }}] {{ source.title }}</strong>
            <p class="muted">版本 {{ source.version }} · {{ source.kind === 'platform' ? '平台规则，非医学依据' : '医学资料审核记录' }}</p>
            <a v-if="/^https?:\/\//.test(source.source)" :href="source.source" target="_blank" rel="noopener noreferrer">{{ source.source }}</a>
            <span v-else class="muted">{{ source.source }}</span>
            <p>{{ source.excerpt }}</p>
          </article>
        </details>
      </article>
      <p v-if="loading" class="loading-label"><el-icon class="is-loading"><Loading /></el-icon>正在生成回答…</p>
    </div>
    <el-button v-if="!followLatest && messages.length" class="jump-latest" :icon="ArrowDown" circle
      aria-label="回到最新消息" title="回到最新消息" @click="scrollLatest" />
    </div>

    <footer class="composer-area">
      <div v-if="draftSelection.length" class="selection-dock">
        <button type="button" class="selection-trigger" @click="selectionOpen = true">
          <el-icon><ShoppingCart /></el-icon><strong>已选 {{ draftSelection.length }} 种</strong>
          <span class="selection-status">{{ blockers.length ? '有待核对项' : '待授权' }}</span><el-icon><ArrowRight /></el-icon>
        </button>
        <el-button size="small" plain type="primary" :disabled="loading || loadingHistory || authorizing" @click="selectionOpen = true">核对清单</el-button>
      </div>
      <form class="input-area" @submit.prevent="sendMessage">
        <textarea v-model="userInput" maxlength="4000" rows="2" aria-label="输入对话内容"
          placeholder="输入问题，或描述想购买的商品与数量…"
          :disabled="loading || loadingHistory || !userStore.isLoggedIn"
          @keydown.ctrl.enter.prevent="sendMessage" @keydown.meta.enter.prevent="sendMessage" />
        <div class="composer-actions">
          <span class="input-hint">Ctrl / ⌘ + Enter 发送</span>
          <div class="send-actions"><span class="character-count">{{ userInput.length }} / 4000</span>
            <el-button v-if="loading" :icon="VideoPause" plain @click="cancelResponse">停止生成</el-button>
            <el-button v-else type="primary" :icon="Position" native-type="submit"
              :disabled="loadingHistory || authorizing || !conversationId || !userInput.trim()">发送</el-button>
          </div>
        </div>
      </form>
      <p class="composer-note">AI建议仅供参考 · {{ commerceEnabled ? '钱包可授权限额智能下单' : '清单核对后再授权' }}</p>
    </footer>

    <el-drawer v-model="selectionOpen" title="待核对清单" size="min(420px, 100vw)" append-to-body>
      <p class="drawer-note">清单尚未授权、未下单。核对商品和数量后，可单独授权AI准备未付款草稿；草稿不扣款、不占库存。</p>
      <article v-for="item in draftSelection" :key="item.id" class="selection-row">
        <div class="product-heading"><strong>{{ item.name }}</strong>
          <el-button :icon="Close" text circle :aria-label="'移除' + item.name" :disabled="authorizing"
            @click="toggleDraftSelection(item, false)" />
        </div>
        <p class="product-meta">商品 {{ item.id }} · 单价 ¥{{ item.price }} · 库存 {{ item.stock }}</p>
        <el-input-number v-model="draftQuantities[item.id]" :min="1" :max="99" :precision="0"
          size="small" controls-position="right" placeholder="数量" :aria-label="item.name + '的核对数量'" :disabled="authorizing" />
      </article>
      <el-empty v-if="!draftSelection.length" description="暂未选择商品" :image-size="70" />
      <div v-if="blockers.length" class="selection-blockers" role="status">
        <strong>暂不能准备草稿</strong><p v-for="reason in blockers" :key="reason">{{ reason }}</p>
        <span>仍可调整选择与数量，销售资格须由服务端审核通过。</span>
      </div>
      <template #footer>
        <div class="selection-footer">
          <el-button type="primary" :loading="authorizing" :disabled="!draftSelection.length || blockers.length > 0 || loading || loadingHistory"
            @click="authorizeProducts(draftSelection)">授权AI准备草稿（不付款）</el-button>
          <RouterLink to="/drafts" @click="selectionOpen = false">查看已保存的草稿</RouterLink>
        </div>
      </template>
    </el-drawer>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import API from "../api/index.js";
import { createAIClient } from "@/services/aiClient.mjs";
import { useUserStore } from "@/stores/userStore";
import { toolRows, toolLabel } from "@/services/toolEvents.mjs";
import { ElMessage } from "element-plus";
import { canSelectProduct, selectionBlockers, proposalSelection } from "@/services/purchaseSelection.mjs";
import { consumeOrderGrant } from "@/services/orderAuthorization.mjs";
import { commerceEnabled, createCommerceClient, fulfillAutoProposal } from "@/services/commerceClient.mjs";
import { Plus, Refresh, InfoFilled, ChatDotRound, User, Loading, ShoppingCart, ArrowRight, ArrowDown, VideoPause, Position, Close } from "@element-plus/icons-vue";

const userStore = useUserStore();
const commerce = createCommerceClient();
const client = createAIClient({
  getDelegation: () => API.agentToken(),
  baseURL: import.meta.env.VITE_AI_BASE || "",
});
const conversations = ref([]);
const conversationId = ref("");
const messages = ref([]);
const userInput = ref("");
const loading = ref(false);
const loadingHistory = ref(false);
const errorText = ref("");
const chatbox = ref(null);
const draftQuantities = ref({});
const authorizing = ref(false);
const draftSelection = ref([]);
const blockers = computed(() => selectionBlockers(draftSelection.value, draftQuantities.value));
const selectionOpen = ref(false);
const followLatest = ref(true);

function trackScroll() {
  const panel = chatbox.value;
  if (panel) followLatest.value = panel.scrollHeight - panel.scrollTop - panel.clientHeight < 64;
}

function scrollLatest() {
  followLatest.value = true;
  if (chatbox.value) chatbox.value.scrollTop = chatbox.value.scrollHeight;
}

const toolState = (tool, message) => tool.status === "running"
  ? message.status === "processing" ? "查询中" : "未完成"
  : tool.status === "completed" ? "已完成" : "查询失败";

function toolExpanded(tool, message) {
  if (tool.tool === "list_inventory" || tool.tool === "analyze_inventory") return false;
  if (message.autoResult?.status === "PAID" && tool.status === "completed") return false;
  const hasProposal = message.toolEvents?.some(entry => entry.data.result?.proposal);
  return tool.tool === "propose_purchase" || tool.tool === "prepare_order_draft"
    || tool.status !== "completed" || !hasProposal;
}
let controller;
let version = 0;
let orderEpoch = 0;

const statusLabel = (status) => ({
  processing: "生成中，可稍后刷新",
  failed: "回答未完成",
  interrupted: "回答已中断",
}[status] || status);

function showHistory(history) {
  messages.value = history.turns.flatMap((turn) => [
    { sender: "user", content: turn.message },
    { sender: "bot", content: turn.assistant || "（暂无回答）", status: turn.status,
      autoTurnId: turn.requestId,
      citations: turn.citations || [], retrieval: turn.retrieval,
      personalizationApplied: turn.personalizationApplied, toolEvents: turn.toolEvents || [] },
  ]);
  for (const turn of history.turns) for (const entry of turn.toolEvents || []) initializeQuantities(entry.data.result);
}

function initializeQuantities(result) {
  for (const product of result?.products || []) {
    if (!(product.id in draftQuantities.value)) {
      draftQuantities.value[product.id] = result.requestedQuantity ?? null;
    }
  }
  if (result?.ok && result.proposal) {
    const selection = proposalSelection(result.proposal);
    draftQuantities.value = { ...draftQuantities.value, ...selection.quantities };
  }
}

function useProposal(proposal) {
  const selection = proposalSelection(proposal);
  draftQuantities.value = { ...draftQuantities.value, ...selection.quantities };
  draftSelection.value = selection.products;
}

async function loadConversations(createNew = false, selected = "") {
  followLatest.value = true;
  orderEpoch++;
  selectionOpen.value = false;
  draftSelection.value = [];
  draftQuantities.value = {};
  const current = ++version;
  controller?.abort();
  controller = new AbortController();
  const signal = controller.signal;
  loadingHistory.value = true;
  errorText.value = "";
  try {
    let created;
    if (createNew) created = await client.create(signal);
    const list = await client.list(signal);
    if (current !== version) return;
    conversations.value = list;
    let id = created?.id || selected || list[0]?.id;
    if (!id) id = (await client.create(signal)).id;
    const history = await client.history(id, signal);
    if (current !== version) return;
    conversationId.value = id;
    showHistory(history);
    if (commerceEnabled) {
      const owner = { token: userStore.token, userId: userStore.userId };
      try {
        const outcomes = await commerce.history(id, owner);
        if (current !== version || owner.token !== userStore.token) return;
        for (const outcome of outcomes) {
          const message = messages.value.find(item => item.autoTurnId === outcome.turnId);
          if (message && ['PAID', 'REJECTED'].includes(outcome.status)) message.autoResult = outcome;
          else if (message && outcome.status === 'READY' && sessionStorage.getItem(autoPendingKey(owner, outcome.turnId))) message.autoResult = { status: 'UNKNOWN', message: '本轮下单结果待核实，请查询原轮次，勿重复购买。' };
        }
      } catch {}
    }
    if (!list.some((item) => item.id === id)) conversations.value = await client.list(signal);
  } catch (error) {
    if (error.name !== "AbortError" && current === version) errorText.value = error.message;
  } finally {
    if (current === version) loadingHistory.value = false;
  }
}

const newConversation = () => loadConversations(true);
const loadSelected = () => loadConversations(false, conversationId.value);

async function sendMessage() {
  const text = userInput.value.trim();
  if (authorizing.value) return;
  return deliver(text);
}

async function deliver(text, orderPreparation) {
  if (!text || loading.value || loadingHistory.value || !conversationId.value) return;
  followLatest.value = true;
  controller?.abort();
  controller = new AbortController();
  const signal = controller.signal;
  const current = ++version;
  const owner = { token: userStore.token, userId: userStore.userId };
  const isCurrent = () => current === version && owner.token === userStore.token && owner.userId === userStore.userId;
  const turnId = crypto.randomUUID();
  let autoTurn;
  const proposals = [];
  const bot = { sender: "bot", content: "", status: "processing", toolEvents: [] };
  messages.value.push({ sender: "user", content: text }, bot);
  const index = messages.value.length - 1;
  userInput.value = "";
  loading.value = true;
  errorText.value = "";
  try {
    if (commerceEnabled && !orderPreparation) {
      try { autoTurn = await commerce.register({ turnId, conversationId: conversationId.value, message: text }, owner); }
      catch (error) {
        if (isCurrent()) messages.value[index].autoResult = { status: "MANUAL", message: "智能下单授权未确认，本轮仅生成清单。" };
      }
      if (!isCurrent() || signal.aborted) return;
    }
    await client.stream(conversationId.value, text, turnId, (kind, data) => {
      if (current !== version) return;
      if (kind === "delta") messages.value[index].content += data.text;
      if (kind === "done") messages.value[index].status = "completed";
      if (kind === "context") Object.assign(messages.value[index], data);
      if (["tool_started", "tool_result"].includes(kind)) {
        messages.value[index].toolEvents.push({ kind, data });
        initializeQuantities(data.result);
        if (!orderPreparation && data.result?.ok && data.result.proposal) {
          useProposal(data.result.proposal);
          proposals.push({ ...data.result.proposal, riskAssessment: data.result.riskAssessment });
        }
      }
    }, signal, orderPreparation);
    if (autoTurn?.status === "READY" && proposals.length === 1 && isCurrent() && !signal.aborted) {
      // Auth is captured from this turn; a late callback never borrows the current account's token.
      messages.value[index].autoTurnId = turnId;
      try {
        const result = await fulfillAutoProposal({ proposal: proposals[0], turn: autoTurn, owner, isCurrent, client: commerce,
          onAttempt: id => {
            try { sessionStorage.setItem(autoPendingKey(owner, id), '1'); }
            catch { throw Object.assign(new Error('无法保存原请求核对标识，本轮未自动扣款，请手动核对。'), { outcome: 'NOT_APPLIED' }); }
          },
        });
        if (result && isCurrent()) {
          messages.value[index].autoResult = result;
          if (['PAID', 'REJECTED'].includes(result.status)) clearAutoPending(owner, turnId);
          if (result.status === "PAID") {
            draftSelection.value = [];
          }
        }
      } catch (error) {
        if (error.outcome !== 'UNKNOWN') clearAutoPending(owner, turnId);
        if (isCurrent()) messages.value[index].autoResult = {
          status: error.outcome === "UNKNOWN" ? "UNKNOWN" : "REJECTED", message: error.message,
        };
      }
    }
  } catch (error) {
    if (current !== version) return;
    messages.value[index].status = error.name === "AbortError" ? "interrupted" : "failed";
    if (error.name !== "AbortError") errorText.value = error.message;
    if (error.code === "UNAUTHORIZED") client.resetAuthorization();
  } finally {
    if (current === version) loading.value = false;
  }
}

const autoPendingKey = (owner, id) => 'auto-order-pending:' + owner.userId + ':' + id;
function clearAutoPending(owner, id) { try { sessionStorage.removeItem(autoPendingKey(owner, id)); } catch {} }

async function checkAutoResult(message) {
  const owner = { token: userStore.token, userId: userStore.userId };
  try {
    const result = await commerce.read(message.autoTurnId, owner);
    if (owner.token !== userStore.token) return;
    if (['PAID', 'REJECTED'].includes(result.status)) clearAutoPending(owner, message.autoTurnId);
    message.autoResult = result.status === "READY" ? { status: "UNKNOWN", message: "尚无已提交的付款记录。请勿重复发送购买消息。" } : result;
  } catch (error) { if (owner.token === userStore.token) ElMessage.error(error.message); }
}

function toggleDraftSelection(product, checked) {
  if (!checked) draftSelection.value = draftSelection.value.filter(item => item.id !== product.id);
  else if (!draftSelection.value.some(item => item.id === product.id)) {
    if (draftSelection.value.length >= 10) ElMessage.error("每次草稿最多10种商品");
    else draftSelection.value.push(product);
  }
}

async function authorizeProducts(products) {
  if (loading.value || loadingHistory.value || authorizing.value || !products.length
    || products.length > 10) return;
  const problems = selectionBlockers(products, draftQuantities.value);
  if (problems.length) {
    ElMessage.error(problems[0]);
    return;
  }
  const items = products.map(product => ({ medicineId: product.id, quantity: draftQuantities.value[product.id] }));
  if (items.some(item => !Number.isInteger(item.quantity) || item.quantity < 1 || item.quantity > 99)) {
    ElMessage.error("数量必须是1至99的整数");
    return;
  }
  const user = userStore.userId;
  const conversation = conversationId.value;
  const ownerToken = userStore.token;
  const orderVersion = ++orderEpoch;
  authorizing.value = true;
  selectionOpen.value = false;
  try {
    await consumeOrderGrant({
      issue: () => API.orderAgentToken({ items }, ownerToken),
      isCurrent: () => orderVersion === orderEpoch && user === userStore.userId && conversation === conversationId.value,
      discard: (grant) => API.revokeOrderGrant(grant.requestKey, ownerToken),
      use: (grant) => {
        const description = items.map(item => `商品ID ${item.medicineId} 数量 ${item.quantity}`).join("；");
        return deliver(`请为我本次明确授权的${description}准备未付款草稿，不要确认或付款。`, grant);
      },
    });
  } catch (error) {
    if (user === userStore.userId) ElMessage.error(error.message || "订单准备失败，请查看我的草稿核对结果");
  } finally {
    if (orderVersion === orderEpoch) authorizing.value = false;
  }
}

async function revokeOrderPreparation() {
  orderEpoch++;
  authorizing.value = false;
  controller?.abort();
  try {
    await API.revokeOrderAgent();
    controller?.abort();
    ElMessage.success("订单准备授权已撤销；已生成的草稿仍可在我的草稿中查看");
  } catch (error) {
    ElMessage.error(error.message || "撤销失败，请重试");
  }
}

const cancelResponse = () => controller?.abort();

function clearSession() {
  selectionOpen.value = false;
  orderEpoch++;
  version++;
  controller?.abort();
  client.resetAuthorization();
  conversations.value = [];
  conversationId.value = "";
  messages.value = [];
  draftQuantities.value = {};
  draftSelection.value = [];
  authorizing.value = false;
  userInput.value = "";
  errorText.value = "";
  loading.value = false;
  loadingHistory.value = false;
}

watch(() => userStore.userId, () => {
  clearSession();
  if (userStore.isLoggedIn) loadConversations();
}, { immediate: true });

watch(messages, async () => {
  await nextTick();
  if (followLatest.value) scrollLatest();
}, { deep: true });

window.addEventListener("auth-cleared", clearSession);
window.addEventListener("profile-context-changed", cancelResponse);
onBeforeUnmount(() => {
  clearSession();
  window.removeEventListener("auth-cleared", clearSession);
  window.removeEventListener("profile-context-changed", cancelResponse);
});
</script>

<style scoped>
.chat-wrapper { width: 100%; max-width: 1120px; height: 100%; min-height: 0; margin: 0 auto; display: grid; grid-template-rows: auto minmax(0, 1fr) auto; border: 1px solid #e4e7ed; border-radius: 8px; background: #fff; overflow: hidden; }
.chat-header { min-width: 0; display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 14px 20px; border-bottom: 1px solid #ebeef5; }
.chat-title { flex-shrink: 0; }
.chat-title h2 { margin: 0; font-size: 17px; font-weight: 600; line-height: 1.5; }
.chat-title > span { color: #909399; font-size: 12px; line-height: 1.7; }
.chat-toolbar { display: flex; align-items: center; gap: 8px; min-width: 0; }
.chat-toolbar :deep(.el-button + .el-button) { margin-left: 0; }
.conversation-select { width: 200px; min-width: 100px; }
.conversation-stage { min-width: 0; min-height: 0; position: relative; }
.chatbox { height: 100%; min-width: 0; min-height: 0; overflow-y: auto; overflow-x: hidden; padding: 20px 28px; overscroll-behavior: contain; scrollbar-gutter: stable; }
.jump-latest { position: absolute; right: 18px; bottom: 12px; background: #fff; border-color: #c6e2ff; color: #409eff; }
.empty-state { min-height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 28px 12px; text-align: center; color: #909399; }
.empty-state > .el-icon { color: #79bbff; margin-bottom: 16px; }
.empty-state h3 { margin: 0 0 8px; color: #303133; font-size: 20px; font-weight: 500; }
.empty-state p { margin: 0; line-height: 1.8; }
.empty-login { display: inline-block; margin-top: 20px; padding: 8px 18px; border: 1px solid #b3d8ff; border-radius: 5px; background: #ecf5ff; font-size: 14px; }
.message { max-width: 100%; margin: 0 0 26px; }
.message-heading { display: flex; align-items: center; gap: 7px; margin-bottom: 8px; color: #606266; font-size: 12px; }
.message-heading .el-icon { color: #409eff; font-size: 16px; }
.message-content { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.8; font-size: 14px; color: #303133; }
.message.user { width: fit-content; max-width: 82%; margin-left: auto; }
.message.user .message-heading { justify-content: flex-end; }
.message.user .message-content { padding: 11px 15px; border-radius: 7px; background: #ecf5ff; }
.message-meta { display: flex; flex-wrap: wrap; gap: 6px 14px; margin-top: 9px; color: #909399; font-size: 11px; line-height: 1.5; }
.loading-label { display: flex; align-items: center; gap: 7px; color: #909399; font-size: 13px; margin: 12px 0; }
.tool-card { margin: 12px 0; border: 1px solid #e4e7ed; border-radius: 6px; background: #fff; overflow: hidden; }
.tool-card > summary { padding: 10px 12px; cursor: pointer; color: #606266; font-size: 13px; background: #fafbfc; line-height: 1.6; }
.tool-card > summary::marker { color: #909399; font-size: 11px; }
.tool-status { float: right; margin-left: 12px; font-size: 11px; color: #909399; }
.tool-status.completed { color: #529b2e; }
.tool-status.failed { color: #c45656; }
.tool-body { padding: 0 14px 12px; font-size: 13px; line-height: 1.7; overflow-wrap: anywhere; }
.tool-body > p { margin: 12px 0 0; }
.product-row { border-bottom: 1px solid #f0f2f5; padding: 13px 0; }
.product-row:last-child { border-bottom: 0; padding-bottom: 4px; }
.product-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.product-heading strong { font-size: 14px; color: #303133; font-weight: 500; }
.price { color: #303133; font-weight: 500; white-space: nowrap; }
.product-meta, .muted { color: #909399; font-size: 12px; }
.product-meta { margin-top: 4px; }
.product-controls { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; margin-top: 9px; }
.product-controls :deep(.el-input-number), .selection-row :deep(.el-input-number) { width: 112px; }
.product-controls :deep(.el-checkbox) { height: 26px; margin-right: 0; }
.product-controls :deep(.el-checkbox__label) { font-size: 12px; }
.blocked-text { margin: 5px 0; color: #b88230; font-size: 12px; line-height: 1.6; }
.proposal > .muted { margin: 12px 0 0; }
.proposal > .el-button { margin-top: 9px; font-size: 12px; }
.business-result { padding-top: 12px; }
.business-result p { margin: 6px 0; }
.snapshot-note { display: block; margin-top: 10px; color: #909399; font-size: 11px; }
.sources { border-top: 1px solid #ebeef5; margin-top: 12px; color: #909399; font-size: 12px; }
.sources summary { padding-top: 10px; cursor: pointer; }
.sources article { padding: 12px 0; line-height: 1.7; color: #606266; overflow-wrap: anywhere; }
.sources article + article { border-top: 1px solid #ebeef5; }
.sources p { margin: 5px 0; }
.composer-area { padding: 12px 20px 10px; border-top: 1px solid #ebeef5; background: #fff; }
.selection-dock { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 6px 10px; margin-bottom: 9px; border-radius: 5px; background: #f5f7fa; }
.selection-trigger { display: flex; align-items: center; gap: 8px; min-width: 0; border: 0; background: transparent; color: #606266; font-size: 12px; cursor: pointer; padding: 4px 0; }
.selection-trigger > .el-icon:first-child { color: #409eff; font-size: 17px; }
.selection-trigger strong { font-weight: 500; white-space: nowrap; }
.selection-status { color: #909399; font-size: 11px; }
.input-area { border: 1px solid #dcdfe6; border-radius: 6px; padding: 9px 11px; transition: border-color .15s; }
.input-area:focus-within { border-color: #409eff; }
.input-area textarea { display: block; width: 100%; height: 54px; min-height: 44px; max-height: 130px; padding: 0; border: 0; outline: none; resize: vertical; background: transparent; color: #303133; line-height: 1.7; font: inherit; }
.input-area textarea::placeholder { color: #a8abb2; }
.input-area textarea:disabled { cursor: not-allowed; }
.composer-actions { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 5px; }
.input-hint, .character-count { color: #a8abb2; font-size: 11px; }
.send-actions { display: flex; align-items: center; gap: 12px; }
.send-actions .el-button { min-width: 82px; height: 31px; }
.composer-note { margin: 7px 0 0; text-align: center; color: #909399; font-size: 11px; line-height: 1.5; }
.help-content { line-height: 1.8; color: #606266; font-size: 13px; }
.help-content p { margin: 8px 0; }
.help-content > .el-button { display: block; margin-top: 8px; }
.drawer-note { color: #909399; font-size: 12px; line-height: 1.8; margin: 0 0 10px; }
.selection-row { padding: 12px 0; border-bottom: 1px solid #ebeef5; }
.selection-row > .el-input-number { margin-top: 10px; }
.selection-row > .product-meta { line-height: 1.6; }
.selection-blockers { margin-top: 18px; padding: 12px; background: #fdf6ec; border-radius: 5px; color: #b88230; font-size: 12px; line-height: 1.8; }
.selection-blockers strong { font-weight: 500; }
.selection-blockers p { margin: 6px 0; }
.selection-blockers > span { color: #909399; }
.selection-footer { display: grid; gap: 12px; text-align: center; font-size: 12px; }
.selection-footer > .el-button { width: 100%; }
@media (max-width: 1000px) {
  .chat-header { padding: 12px 16px; }
  .chat-title > span { display: none; }
  .conversation-select { width: 160px; }
  .chatbox { padding: 18px; }
}
@media (max-width: 600px) {
  .chat-header { flex-wrap: wrap; gap: 9px; padding: 11px 12px; }
  .chat-title { width: 100%; }
  .chat-title h2 { font-size: 16px; }
  .chat-toolbar { width: 100%; }
  .conversation-select { width: auto; flex: 1; }
  .chat-toolbar > .el-button:not(.is-circle) { padding: 8px 10px; }
  .chatbox { padding: 16px 12px; }
  .message.user { max-width: 92%; }
  .composer-area { padding: 9px 10px 8px; }
  .input-area textarea { height: 48px; max-height: 104px; }
  .input-hint { display: none; }
  .composer-actions { justify-content: flex-end; }
  .selection-status { display: none; }
  .empty-state h3 { font-size: 18px; }
  .empty-state p { font-size: 12px; }
}
</style>
