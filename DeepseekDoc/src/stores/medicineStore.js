//medicineStore.js
import { defineStore } from "pinia";
import { ref, computed } from "vue";
import { ElMessage } from "element-plus";
import API from "@/components/api";

export const useMedicineStore = defineStore("medicine", () => {
  const medicines = ref([]);
  const tableRefreshKey = ref(0);

  const medicineCount = computed(() => medicines.value.length);

  async function fetchMedicines(name = "") {
    try {
      const list = await API.getMedicines(name);
      medicines.value = list.map((med) => ({
        id: Number(med.id),
        name: med.name,
        price: Number(med.price),
        stock: med.stock,
        tempStock: med.stock,
        draftEligible: med.draftEligible === true,
        draftBlockedReason: med.draftBlockedReason || "商品资格待核验",
      }));
    } catch (err) {
      ElMessage.error("获取药品列表失败：" + (err.message || ""));
      medicines.value = [];
    }
  }

  const getMedicineById = (id) => {
    return medicines.value.find((m) => m.id === Number(id)) || null;
  };

  // 更新临时库存（视图层使用）
  function updateTempStock(medicineId, delta) {
    const idx = medicines.value.findIndex((m) => m.id === Number(medicineId));
    if (idx === -1) return;
    const m = medicines.value[idx];
    const newTemp = Math.max(0, m.tempStock + delta);
    medicines.value.splice(idx, 1, { ...m, tempStock: newTemp });
    tableRefreshKey.value++;
  }

  // 更新实际库存（仅订单成功时调用）
  function updateStock(medicineId, delta) {
    const idx = medicines.value.findIndex((m) => m.id === Number(medicineId));
    if (idx === -1) return;
    const m = medicines.value[idx];
    const newStock    = Math.max(0, m.stock + delta);
    const newTempStock = Math.max(0, m.tempStock + delta);
    medicines.value.splice(idx, 1, {
      ...m,
      stock: newStock,
      tempStock: newTempStock,
    });
    tableRefreshKey.value++;
  }

  const validateStock = (medicineId, requestedQuantity) => {
    const medicine = medicines.value.find((m) => m.id === medicineId);
    return medicine && medicine.stock >= requestedQuantity;
  };

  return {
    medicines,
    tableRefreshKey,
    fetchMedicines,
    updateTempStock, 
    updateStock,
    validateStock,
    getMedicineById,
  };
});
