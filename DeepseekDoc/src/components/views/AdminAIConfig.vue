<script setup>
import { onMounted, ref } from 'vue';
import { useUserStore } from '@/stores/userStore';
import { createCommerceClient } from '@/services/commerceClient.mjs';
const user = useUserStore();
const client = createCommerceClient();
const config = ref(null);
const busy = ref(false);
const apiKey = ref('');
const clearApiKey = ref(false);
const message = ref('');
const owner = () => ({ token: user.token });
async function load() {
  const captured = owner();
  try { const value = await client.modelConfig(captured); if (captured.token === user.token) config.value = { ...value, protocol: value.protocol || 'ollama' }; }
  catch (error) { message.value = error.message; }
}
async function save() {
  busy.value = true;
  const captured = owner();
  try {
    const value = await client.saveModelConfig({ expectedVersion: config.value.version, model: config.value.model, endpoint: config.value.endpoint, protocol: config.value.protocol, apiKey: apiKey.value || undefined, clearApiKey: clearApiKey.value }, captured);
    if (captured.token === user.token) { config.value = value; message.value = '已保存，新模型请求使用此配置。'; }
  } catch (error) { message.value = error.message; }
  finally { apiKey.value = ''; clearApiKey.value = false; busy.value = false; }
}
onMounted(load);
</script>
<template>
  <section class="config-page">
    <h2>AI 模型配置</h2>
    <p>支持 Ollama 与 OpenAI 兼容 Chat Completions 协议，模型须支持工具调用。</p>
    <p>更换 endpoint 后，对话与已授权上下文将发送至该服务。RAG 嵌入模型配置保持独立。</p>
    <el-alert v-if="message" :title="message" :closable="false" />
    <el-form v-if="config" label-position="top" :disabled="busy" @submit.prevent="save">
      <el-form-item label="协议"><el-radio-group v-model="config.protocol"><el-radio value="ollama">Ollama</el-radio><el-radio value="openai">OpenAI 兼容（DeepSeek 等）</el-radio></el-radio-group></el-form-item>
      <p v-if="config.protocol === 'openai'">Endpoint 填 API 基础地址，例如 https://api.deepseek.com 或服务商提供的 /v1 地址。</p>
      <el-form-item label="模型名称"><el-input v-model="config.model" maxlength="100" placeholder="例如 qwen2.5:7b" /></el-form-item>
      <el-form-item label="Endpoint"><el-input v-model="config.endpoint" maxlength="500" placeholder="http://127.0.0.1:11434" /></el-form-item>
      <el-form-item label="API Key"><el-input v-model="apiKey" type="password" autocomplete="off" maxlength="500" :placeholder="config.hasApiKey ? '已配置，留空保留；更换地址或协议需重新填写' : '填写服务商API Key，不会回显'" /></el-form-item>
      <el-checkbox v-model="clearApiKey">清除已保存的 API Key</el-checkbox>
      <p>切换地址或协议时，旧密钥不会自动发送到新服务。</p>
      <el-button type="primary" :loading="busy" @click="save">保存配置</el-button>
      <el-button @click="load">重新读取</el-button>
    </el-form>
  </section>
</template>
<style scoped>
.config-page { max-width: 760px; padding: 24px; margin: auto; }
h2 { font-size: 21px; }
p { color: #909399; font-size: 13px; line-height: 1.8; }
.el-form { margin-top: 24px; }
</style>
