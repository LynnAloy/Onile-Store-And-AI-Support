const validKey = key => typeof key === "string" && /^[A-Za-z0-9_-]{8,64}$/.test(key);

export const browserPaymentRecovery = () => createPaymentRecovery({
  getItem: key => sessionStorage.getItem(key),
  setItem: (key, value) => sessionStorage.setItem(key, value),
  removeItem: key => sessionStorage.removeItem(key),
});

export function createPaymentRecovery(storage) {
  const name = (user, id) => `payment-recovery:${encodeURIComponent(user)}:${encodeURIComponent(id)}`;
  return {
    read(user, id) {
      const text = storage.getItem(name(user, id));
      if (!text) return null;
      const row = JSON.parse(text);
      if (!validKey(row.key) || !Number.isSafeInteger(row.version) || row.version < 1) throw new Error("付款恢复标记无效，请先查询原订单");
      return { key: row.key, version: row.version, retryable: row.retryable === true };
    },
    write(user, id, row) {
      if (!validKey(row.key) || !Number.isSafeInteger(row.version) || row.version < 1) throw new Error("付款恢复标记无效");
      // Store only recovery coordinates, never PINs, parent tokens or payment capabilities.
      storage.setItem(name(user, id), JSON.stringify({ key: row.key, version: row.version, retryable: row.retryable === true }));
    },
    clear(user, id) { storage.removeItem(name(user, id)); },
    checkoutKey(user, draft, version, makeKey) {
      const key = `draft-checkout:${encodeURIComponent(user)}:${encodeURIComponent(draft)}:${version}`;
      const prior = storage.getItem(key);
      if (prior && !validKey(prior)) throw new Error("草稿恢复标记无效，请先检查已有订单");
      if (prior) return prior;
      const value = makeKey();
      if (!validKey(value)) throw new Error("无法生成请求键");
      storage.setItem(key, value);
      return value;
    },
  };
}
