export function canSelectProduct(product, selected, busy = false) {
  if (!product || !Number.isSafeInteger(product.id) || product.id < 1 || busy) return false;
  return selected.some(item => item.id === product.id) || selected.length < 10;
}

export function selectionBlockers(products, quantities) {
  return products.flatMap(product => {
    const reasons = [];
    const quantity = quantities[product.id];
    if (!product.draftEligible) reasons.push(product.draftBlockedReason || "商品资格待核验");
    if (!Number.isInteger(quantity) || quantity < 1 || quantity > 99) reasons.push("请填写1至99的整数数量");
    else if (quantity > product.stock) reasons.push("库存不足，请调整数量或稍后重试");
    return reasons.map(reason => product.name + "：" + reason);
  });
}

export function proposalSelection(proposal) {
  if (proposal?.requiresUserAuthorization !== true || !Array.isArray(proposal.items)) {
    throw new Error("购买清单格式异常");
  }
  return {
    products: proposal.items.filter(item => item.autoSelect === true),
    quantities: Object.fromEntries(proposal.items.map(item => [item.id, item.quantity])),
  };
}

