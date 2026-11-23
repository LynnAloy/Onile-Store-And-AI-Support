export function emptyHealthProfile() {
  return {
    name: "", age: null, gender: null, birthday: null, phoneNum: "", address: "", medical: [],
    heightCm: null, weightKg: null, medicalHistoryText: "", allergiesText: "",
    medicationsText: "", lifestyleText: "", healthNotes: "", aiProfileConsent: false,
    profileContextVersion: 0, profileConsentUpdatedAt: 0,
  };
}

function numeric(value, minimum, maximum, integer = false) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  if (!Number.isFinite(number) || number < minimum || number > maximum
    || (integer && !Number.isInteger(number))) throw new Error("健康数值超出允许范围或格式不正确");
  if (!integer && Math.abs(number * 10 - Math.round(number * 10)) > 0.000001) {
    throw new Error("身高体重最多保留一位小数");
  }
  return number;
}

export function profilePayload(userId, userInfo, health) {
  return {
    basic: {
      userId,
      nickname: userInfo.nickname || userId,
      email: userInfo.email || "",
      name: health.name || "",
      age: numeric(health.age, 0, 120, true),
      gender: health.gender || null,
      birthday: health.birthday || null,
      phoneNum: health.phoneNum || "",
      address: health.address || "",
      medicalHistory: Array.isArray(health.medical) ? health.medical : [],
    },
    health: {
      heightCm: numeric(health.heightCm, 30, 260),
      weightKg: numeric(health.weightKg, 1, 500),
      medicalHistoryText: health.medicalHistoryText || "",
      allergiesText: health.allergiesText || "",
      medicationsText: health.medicationsText || "",
      lifestyleText: health.lifestyleText || "",
      healthNotes: health.healthNotes || "",
      aiProfileConsent: health.aiProfileConsent === true,
    },
  };
}
