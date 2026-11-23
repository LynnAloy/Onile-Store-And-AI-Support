// Run inside Codex's cua_repl; every browser action uses the documented CUA API.
// await (await import('file:///.../scripts/m43-browser.cua.mjs')).run({ cua, browser, fs, root });
export async function run({ cua, browser, fs, root }) {
  const account = JSON.parse(await fs.readFile(`${root}/.local-demo/browser-account.json`, "utf8"));
  const output = `${root}/docs/evidence/m43`;
  await fs.mkdir(output, { recursive: true });
  const tab = await cua.createBrowserTab("iab", "http://127.0.0.1:13000/main", { visible: false });
  const page = tab.playwright;
  const viewport = await browser.capabilities.get("viewport");
  const checks = [];
  const snapshot = async () => tab.getAXState({ emit: false });
  const wait = async (locator, state) => {
    const deadline = Date.now() + 180000;
    while (true) {
      try { return await locator.waitFor({ state, timeoutMs: 5000 }); }
      catch (error) { if (Date.now() >= deadline) throw error; }
    }
  };
  const record = async (name, details = {}) => {
    checks.push({ name, passed: true, ...details });
    await fs.writeFile(`${output}/browser-results.json`, JSON.stringify({ passed: false, running: true, checks }, null, 2));
  };
  const purchase = async (text) => {
    await page.getByRole("button", { name: "新对话", exact: true }).click();
    await snapshot();
    await page.getByRole("textbox", { name: "输入对话内容" }).fill(text);
    await page.getByRole("textbox", { name: "输入对话内容" }).press("Control+Enter");
    await snapshot();
    await wait(page.getByRole("button", { name: "停止生成", exact: true }), "hidden");
    return snapshot();
  };
  try {
    await page.getByText("虚构演示", { exact: true }).waitFor({ state: "visible" });
    if (await page.getByRole("button", { name: "个人账号", exact: true }).isVisible()) {
      await page.getByRole("button", { name: "个人账号", exact: true }).click();
      await snapshot();
      await page.getByRole("menuitem", { name: "退出登录", exact: true }).click();
      await snapshot();
    }
    await page.getByRole("button", { name: "登录", exact: true }).click();
    await snapshot();
    await page.getByPlaceholder("请输入用户名").fill(account.userId);
    await page.getByPlaceholder("请输入密码").fill(account.password);
    await page.getByRole("button", { name: "立即登录", exact: true }).click();
    await page.getByRole("button", { name: "新对话", exact: true }).waitFor({ state: "visible" });
    await snapshot();
    await record("login-synthetic-account");
    let state = await purchase("帮我下单5件虚构演示甲，3件虚构演示乙");
    if (!state.includes("请求 5 件") || !state.includes("请求 3 件")) throw new Error("Explicit 5/3 quantities missing");
    const boxes = page.locator(".proposal").getByText("选入清单", { exact: true });
    await boxes.nth(0).click();
    await snapshot();
    await boxes.nth(0).click();
    const quantityControl = page.locator(".proposal").getByRole("spinbutton", { name: "虚构演示甲的数量", exact: true });
    await page.locator(".proposal .product-row").first().getByRole("button", { name: "increase number", exact: true }).click();
    await snapshot();
    if (await quantityControl.evaluate(element => element.value) !== "6") throw new Error("Quantity increment failed");
    await page.locator(".proposal .product-row").first().getByRole("button", { name: "decrease number", exact: true }).click();
    await snapshot();
    if (await quantityControl.evaluate(element => element.value) !== "5") throw new Error("Quantity restore failed");
    await page.getByRole("button", { name: "核对清单", exact: true }).click();
    await snapshot();
    await record("real-native-tools-quantity-checkbox-edit");
    await page.getByRole("button", { name: "授权AI准备草稿（不付款）", exact: true }).click();
    await snapshot();
    await wait(page.getByRole("link", { name: "核对草稿与当前状态", exact: true }).last(), "visible");
    await wait(page.getByRole("button", { name: "停止生成", exact: true }), "hidden");
    await page.getByRole("link", { name: "核对草稿与当前状态", exact: true }).last().click();
    await snapshot();
    const detail = await page.locator(".draft-detail").innerText();
    if (!detail.includes("× 5") || !detail.includes("× 3") || !detail.includes("¥10.00")) throw new Error("Draft differs from reviewed 5/3 quantities");
    await page.getByRole("textbox", { name: "收货人", exact: true }).fill("演示收货人");
    await page.getByRole("textbox", { name: "手机号", exact: true }).fill("13800138000");
    await page.getByRole("textbox", { name: "收货地址", exact: true }).fill("虚构演示地址M43测试楼");
    await page.getByRole("button", { name: "确认资料（不付款）", exact: true }).click();
    await page.getByRole("heading", { name: "已确认资料（未付款）", exact: true }).waitFor({ state: "visible" });
    await snapshot();
    await record("explicit-authorization-private-shipping-confirmed-unpaid");
    await viewport.set({ width: 1366, height: 768 });
    await page.getByRole("heading", { name: "我的草稿", exact: true }).click();
    await snapshot();
    await fs.writeFile(`${output}/confirmed-desktop.png`, await tab.screenshot({ fullPage: false }));
    await page.getByRole("link", { name: "返回对话", exact: true }).click();
    await snapshot();
    for (const size of [{ width: 1366, height: 768 }, { width: 450, height: 668 }, { width: 390, height: 844 }]) {
      await viewport.set(size);
      const layout = await page.evaluate(() => {
        const composer = document.querySelector(".composer-area").getBoundingClientRect();
        const chat = document.querySelector(".chatbox");
        return { width: window.innerWidth, height: window.innerHeight,
          documentWidth: document.documentElement.scrollWidth, documentHeight: document.documentElement.scrollHeight,
          composerTop: composer.top, composerBottom: composer.bottom, chatHeight: chat.clientHeight,
          independentScroll: getComputedStyle(chat).overflowY === "auto" };
      });
      if (layout.documentWidth > size.width || layout.composerBottom > size.height + 1
          || layout.chatHeight < 180 || !layout.independentScroll) throw new Error(`Layout failed: ${JSON.stringify(layout)}`);
      await fs.writeFile(`${output}/chat-${size.width}x${size.height}.png`, await tab.screenshot({ fullPage: false }));
      await record("responsive-composer-independent-scroll", layout);
    }
    state = await purchase("帮我下单2件虚构待审核");
    if (!state.includes("虚构待审核") || !state.includes("审核")) throw new Error("Pending product missing");
    await page.locator(".proposal").getByText("选入清单", { exact: true }).last().click();
    await snapshot();
    await page.locator(".proposal").getByText("选入清单", { exact: true }).last().click();
    await page.getByRole("button", { name: "核对清单", exact: true }).click();
    await snapshot();
    if (await page.getByRole("button", { name: "授权AI准备草稿（不付款）", exact: true }).isEnabled()) throw new Error("Pending product can authorize");
    await fs.writeFile(`${output}/pending-mobile.png`, await tab.screenshot({ fullPage: false }));
    await record("pending-selectable-but-authorization-blocked");
    await page.getByRole("button", { name: "Close this dialog", exact: true }).click();
    await page.getByRole("button", { name: "刷新记录", exact: true }).click();
    await snapshot();
    const value = await page.locator(".proposal").getByRole("spinbutton", { name: "虚构待审核的数量", exact: true }).getAttribute("aria-valuenow");
    if (value !== "2") throw new Error("History lost requested quantity");
    await record("history-preserves-quantity-without-auto-selection");
    await purchase("我想购买虚构演示甲，请给我待核对清单，数量还没有决定。");
    const missingValue = await page.locator(".proposal").getByRole("spinbutton", {
      name: "虚构演示甲的数量", exact: true }).evaluate(element => element.value);
    if (missingValue !== "") throw new Error("Missing quantity silently became a number");
    await page.getByRole("button", { name: "核对清单", exact: true }).click();
    await snapshot();
    if (await page.getByRole("button", { name: "授权AI准备草稿（不付款）", exact: true }).isEnabled()) throw new Error("Missing quantity can authorize");
    await page.getByRole("button", { name: "Close this dialog", exact: true }).click();
    await snapshot();
    await record("missing-quantity-stays-blank-and-blocks-authorization");
    state = await purchase("我想购买2件虚构多规格，请先查询，规格还没有决定。");
    if (!state.includes("原请求数量为2件") || !state.includes("选择具体规格")) throw new Error("Variant clarification lost quantity");
    const variants = await page.getByRole("checkbox", { name: "选入清单", exact: true }).evaluateAll(
      elements => elements.map(element => element.checked));
    if (variants.length !== 2 || variants.some(Boolean)) throw new Error("Variant was automatically selected");
    await record("multiple-variants-require-manual-choice-with-original-quantity");
    await purchase("请查询商品名称包含虚构的商品，最多返回10条。只查询，不要购买。");
    const stressBoxes = page.locator(".tool-card").first().getByText("选入清单", { exact: true });
    if (await stressBoxes.count() !== 10) throw new Error("Stress catalog must show ten fixture products");
    for (let index = 0; index < 10; index++) await stressBoxes.nth(index).click();
    await snapshot();
    await page.getByRole("button", { name: "核对清单", exact: true }).click();
    await snapshot();
    const drawer = await page.evaluate(() => {
      const body = document.querySelector(".el-drawer__body");
      const footer = document.querySelector(".el-drawer__footer").getBoundingClientRect();
      return { bodyHeight: body.clientHeight, contentHeight: body.scrollHeight,
        footerBottom: footer.bottom, viewportHeight: window.innerHeight,
        items: document.querySelectorAll(".selection-row").length };
    });
    if (drawer.items !== 10 || drawer.contentHeight <= drawer.bodyHeight
        || drawer.footerBottom > drawer.viewportHeight + 1) throw new Error("Ten-item drawer controls unreachable");
    await fs.writeFile(`${output}/ten-item-drawer.png`, await tab.screenshot({ fullPage: false }));
    await record("ten-item-drawer-scroll-and-footer-reachable", drawer);
    await page.getByRole("button", { name: "Close this dialog", exact: true }).click();
    await snapshot();
    await page.getByRole("textbox", { name: "输入对话内容" }).fill("长消息布局验收".repeat(400));
    const longLayout = await page.evaluate(() => ({ width: document.documentElement.scrollWidth,
      viewportWidth: window.innerWidth, bottom: document.querySelector(".composer-area").getBoundingClientRect().bottom,
      viewportHeight: window.innerHeight }));
    if (longLayout.width > longLayout.viewportWidth || longLayout.bottom > longLayout.viewportHeight + 1) throw new Error("Long input overflow");
    await page.getByRole("textbox", { name: "输入对话内容" }).fill("");
    await record("long-input-within-viewport", longLayout);
    await page.locator(".chatbox").press("Home");
    await snapshot();
    await wait(page.getByRole("button", { name: "回到最新消息", exact: true }), "visible");
    await page.getByRole("button", { name: "回到最新消息", exact: true }).click();
    await snapshot();
    await record("keyboard-scroll-and-jump-to-latest");
    await page.getByRole("button", { name: "新对话", exact: true }).click();
    await snapshot();
    await page.getByRole("textbox", { name: "输入对话内容" }).fill("请从1开始逐行列出整数，一直列到1000，不要省略。");
    await page.getByRole("textbox", { name: "输入对话内容" }).press("Control+Enter");
    await wait(page.getByRole("button", { name: "停止生成", exact: true }), "visible");
    await snapshot();
    await page.getByRole("button", { name: "停止生成", exact: true }).click();
    await wait(page.getByRole("button", { name: "停止生成", exact: true }), "hidden");
    await snapshot();
    await record("stop-stream-unlocks-composer");
    await page.getByRole("button", { name: "使用说明", exact: true }).click();
    await snapshot();
    await page.getByRole("button", { name: "撤销订单准备授权", exact: true }).click();
    await snapshot();
    await record("revoke-from-chat");
    const boundary = JSON.parse(await fs.readFile(`${root}/.local-demo/browser-boundary-fixtures.json`, "utf8"));
    for (const [kind, id] of Object.entries(boundary)) {
      await tab.goto(`http://127.0.0.1:13000/drafts?id=${id}`);
      await wait(page.locator(".draft-detail"), "visible");
      await page.locator(".detail-heading").click();
      await snapshot();
      if (await page.getByRole("button", { name: "确认资料（不付款）", exact: true }).isEnabled()) throw new Error(`${kind} permits confirmation`);
      const text = await page.locator(".draft-detail").innerText();
      const expected = { price: "价格", stock: "库存", qualification: "审核版本", expiry: "已过期" };
      if (!text.includes(expected[kind])) throw new Error(`${kind} reason not visible`);
      await fs.writeFile(`${output}/boundary-${kind}.png`, await tab.screenshot({ fullPage: false }));
      await record(`business-boundary-visible-${kind}`);
    }
    await page.getByRole("button", { name: "个人账号", exact: true }).click();
    await snapshot();
    await page.getByRole("menuitem", { name: "退出登录", exact: true }).click();
    await wait(page.getByPlaceholder("请输入用户名"), "visible");
    await snapshot();
    await page.getByText("首页对话", { exact: true }).click();
    await wait(page.getByRole("link", { name: "登录后开始对话", exact: true }), "visible");
    await snapshot();
    await record("logout-clears-history-and-purchase-state");
    const alternate = JSON.parse(await fs.readFile(`${root}/.local-demo/browser-alt-account.json`, "utf8"));
    await page.getByRole("button", { name: "登录", exact: true }).click();
    await snapshot();
    await page.getByPlaceholder("请输入用户名").fill(alternate.userId);
    await page.getByPlaceholder("请输入密码").fill(alternate.password);
    await page.getByRole("button", { name: "立即登录", exact: true }).click();
    await wait(page.getByRole("button", { name: "新对话", exact: true }), "visible");
    await snapshot();
    if (await page.locator(".message").count() !== 0) throw new Error("Previous account messages leaked");
    await record("account-switch-has-no-previous-user-history");
    await tab.goto(`http://127.0.0.1:13000/drafts?id=${boundary.price}`);
    await wait(page.locator(".el-alert"), "visible");
    await snapshot();
    if (await page.locator(".draft-detail").count() !== 0) throw new Error("Foreign draft content leaked");
    await fs.writeFile(`${output}/cross-user-denied.png`, await tab.screenshot({ fullPage: false }));
    await record("cross-user-draft-content-denied");
    await page.getByRole("button", { name: "个人账号", exact: true }).click();
    await snapshot();
    await page.getByRole("menuitem", { name: "退出登录", exact: true }).click();
    await snapshot();
    const report = { passed: true, running: false, checks, driver: "Codex CUA", syntheticOnly: true };
    await fs.writeFile(`${output}/browser-results.json`, JSON.stringify(report, null, 2));
    return report;
  } catch (error) {
    await fs.writeFile(`${output}/browser-failure.png`, await tab.screenshot({ fullPage: false }));
    await fs.writeFile(`${output}/browser-results.json`, JSON.stringify({ passed: false, checks, failure: error.message }, null, 2));
    throw error;
  } finally {
    await viewport.reset();
  }
}
