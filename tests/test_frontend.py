"""Tests for the bundled FITAGE dashboard card and its frontend registration."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
from functools import wraps
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.fitage import async_setup
from custom_components.fitage.assessment import ASSESSMENT_LABELS
from custom_components.fitage.frontend import (
    CARD_FILENAME,
    CARD_VERSION,
    LEGACY_PROTOTYPE_URL_PATH,
    MODULE_URL,
    STATIC_URL_PATH,
    async_register_frontend,
)

CARD_PATH = (
    Path(__file__).parents[1] / "custom_components" / "fitage" / "www" / CARD_FILENAME
)

_JS_VERSION_RE = re.compile(r"""const\s+VERSION\s*=\s*["']([^"']+)["']""")

# The 21 FITAGE languages proven complete (17/17 assessment keys) during the
# APK research and approved for implementation; da/sv/fi/no (missing
# "insufficient") and el/is (near-empty stub files) are deliberately not
# included yet. Keys other than "en"/"nl" are FITAGE's own file codes, not
# ISO ones: "jp" (ja), "rus" (ru), "csy" (cs), "fa" (FITAGE's code for
# French, not Persian - see normalizeLanguage()'s HA "fa" -> English block).
FITAGE_SUPPORTED_LANGUAGES = [
    "en",
    "nl",
    "de",
    "es",
    "it",
    "ar",
    "pt",
    "tr",
    "hu",
    "pl",
    "ro",
    "sk",
    "th",
    "vi",
    "ko",
    "jp",
    "rus",
    "csy",
    "zh_CN",
    "zh_TW",
    "fa",
]

# The exact official text bundled in fitage-card.js's LEVEL_LABELS, sourced
# verbatim from the official FITAGE app's own translation files (research
# scratchpad), for every assessment key custom_components/fitage/assessment.py
# can actually produce (ASSESSMENT_LABELS) across all FITAGE_SUPPORTED_LANGUAGES.
# Spelling, casing, accents and script are preserved exactly as researched,
# including apparent source quirks (e.g. Italian/Vietnamese stray
# leading/trailing spaces) - nothing here is invented or machine-translated.
# The English "above_average"/"below_average"/"excellent" values are the
# official app's effective, override-merged text (proven from its own
# appSpecialTranslation data), not the raw, unmerged translation/en.json text.
EXPECTED_LEVEL_LABELS = {
    "above_average": {
        "en": "Above average",
        "nl": "Bovengemiddeld",
        "de": "Überdurchschnittlich",
        "es": "Por encima del promedio",
        "it": "Sopra la media",
        "ar": "فوق المتوسط",
        "pt": "Acima da média",
        "tr": "Ortalamanın üstü",
        "hu": "Átlagon felüli",
        "pl": "Powyżej przeciętnej",
        "ro": "Peste medie",
        "sk": "Nad priemerom",
        "th": "เกินค่าเฉลี่ย",
        "vi": " Trên mức trung bình",
        "ko": "평균 이상",
        "jp": "平均以上",
        "rus": "Свыше нормы",
        "csy": "Nad průměrem",
        "zh_CN": "高于平均值",
        "zh_TW": "高於平均值",
        "fa": "Au-dessus de la moyenne",
    },
    "acceptable": {
        "en": "Acceptable",
        "nl": "Aanvaardbaar",
        "de": "Annehmbar",
        "es": "Aceptable",
        "it": "Accettabile ",
        "ar": "مقبول",
        "pt": "Aceitável",
        "tr": "Normal",
        "hu": "Elfogadható",
        "pl": "Akceptowalny",
        "ro": "Acceptabil",
        "sk": "Prijateľný",
        "th": "ยอมรับได้",
        "vi": " Chấp nhận được",
        "ko": "허용",
        "jp": "許容できる",
        "rus": "Приемлемо",
        "csy": "Přijatelný",
        "zh_CN": "可接受的",
        "zh_TW": "可接受的",
        "fa": "Acceptable",
    },
    "athletes": {
        "en": "Athletes",
        "nl": "Atleten",
        "de": "Sportler",
        "es": "Atletas",
        "it": "Atleta",
        "ar": "الرياضيين",
        "pt": "Atletas",
        "tr": "Atletik",
        "hu": "Sportolók",
        "pl": "Sportowcy",
        "ro": "Sportivi",
        "sk": "Atletický",
        "th": "นักกีฬา",
        "vi": " Vận động viên",
        "ko": "건장한",
        "jp": "壮健",
        "rus": "Спортсмены",
        "csy": "Atletický",
        "zh_CN": "健壮",
        "zh_TW": "健壯",
        "fa": "Vigoureux",
    },
    "average": {
        "en": "Average",
        "nl": "Gemiddeld",
        "de": "Durchschnittlich",
        "es": "Medio",
        "it": "Nella media",
        "ar": "معدل",
        "pt": "Média",
        "tr": "Ortalama",
        "hu": "Átlagos",
        "pl": "Przeciętna",
        "ro": "In medie",
        "sk": "Priemerný",
        "th": "ปานกลาง",
        "vi": " Trung bình",
        "ko": "평균",
        "jp": "平均",
        "rus": "Норма",
        "csy": "Průměrný",
        "zh_CN": "平均水平",
        "zh_TW": "平均水平",
        "fa": "Moyenne",
    },
    "below_average": {
        "en": "Below average",
        "nl": "Ondergemiddeld",
        "de": "Unterdurchschnittlich",
        "es": "Debajo del promedio",
        "it": "Sotto la media ",
        "ar": "أقل من المتوسط",
        "pt": "Abaixo da média",
        "tr": "Ortalamanın altında",
        "hu": "Átlag alatti",
        "pl": "Poniżej przeciętnej",
        "ro": "Sub medie",
        "sk": "Pod priemerom",
        "th": "ต่ำกว่ามาตรฐาน",
        "vi": "Dưới trung bình",
        "ko": "평균 이하",
        "jp": "平均以下の",
        "rus": "Ниже нормы",
        "csy": "Pod průměrem",
        "zh_CN": "低于平均值",
        "zh_TW": "低於平均值",
        "fa": "Sous la moyenne",
    },
    "essential_fat": {
        "en": "Essential Fat",
        "nl": "Essentieel Vet",
        "de": "Essentielles Fett",
        "es": "Grass esencial",
        "it": "Grasso essenziale ",
        "ar": "الدهون الأساسية",
        "pt": "Gordura essencial",
        "tr": "Temel Yağ",
        "hu": "Alapvető zsír",
        "pl": "Tkanka tłuszczowa podstawowa",
        "ro": "Grăsime esențială",
        "sk": "Základné tuk",
        "th": "ไขมันที่จำเป็น",
        "vi": " Chất béo thiết yếu",
        "ko": "마른편",
        "jp": "薄い",
        "rus": "Основной жир",
        "csy": "Základní tuk",
        "zh_CN": "偏瘦",
        "zh_TW": "偏瘦",
        "fa": "Plus maigre",
    },
    "excellent": {
        "en": "Excellent",
        "nl": "Uitstekend",
        "de": "Ausgezeichnet",
        "es": "Suficiente",
        "it": "Adeguato",
        "ar": "كافي",
        "pt": "O bastante",
        "tr": "Yeterli",
        "hu": "Megfelelő",
        "pl": "Doskonałe",
        "ro": "Destul",
        "sk": "Dostačujúce",
        "th": "เพียงพอ",
        "vi": " Đủ",
        "ko": "충족",
        "jp": "十分な",
        "rus": "Приемлемо",
        "csy": "Dostačující",
        "zh_CN": "充足",
        "zh_TW": "充足",
        "fa": "Suffisant",
    },
    "excessive": {
        "en": "Excessive",
        "nl": "Erg hoog",
        "de": "Sehr hoch",
        "es": "Excesivo",
        "it": "Eccessivo",
        "ar": "بشكل مفرط",
        "pt": "Excessivo",
        "tr": "Çok yüksek",
        "hu": "Túlzott",
        "pl": "Nadmierna",
        "ro": "Excesivă",
        "sk": "Prebytočné",
        "th": "ซึ่งมากเกินไป",
        "vi": " Rất cao",
        "ko": "과도",
        "jp": "高すぎ",
        "rus": "Чрезмерное содержание жира ",
        "csy": "Nadměrné",
        "zh_CN": "严重偏高",
        "zh_TW": "嚴重偏高",
        "fa": "Trop.",
    },
    "fitness": {
        "en": "Fitness",
        "nl": "Fitness",
        "de": "Fitness",
        "es": "Sano",
        "it": "Fitness",
        "ar": "اللياقه البدنيه",
        "pt": "Ginástica",
        "tr": "Fit",
        "hu": "Fitness",
        "pl": "Fitness",
        "ro": "Fitness",
        "sk": "Fit",
        "th": "ความแข็งแรง",
        "vi": " Sự thích hợp",
        "ko": "건강",
        "jp": "健康",
        "rus": "В хорошей форме",
        "csy": "Fit",
        "zh_CN": "健康",
        "zh_TW": "健康",
        "fa": "Fort",
    },
    "good": {
        "en": "Good",
        "nl": "Goed",
        "de": "Gut",
        "es": "Bien",
        "it": "Bene",
        "ar": "جيد",
        "pt": "Bom",
        "tr": "İyi",
        "hu": "Jó",
        "pl": "Dobry",
        "ro": "Bun",
        "sk": "Dobre",
        "th": "ดี",
        "vi": "Tốt",
        "ko": "좋은",
        "jp": "良い",
        "rus": "Хороший",
        "csy": "Dobrý",
        "zh_CN": "很好",
        "zh_TW": "很好",
        "fa": "Bien",
    },
    "high": {
        "en": "High",
        "nl": "Hoog",
        "de": "Hoch",
        "es": "Alto",
        "it": "Alto",
        "ar": "مرتفع",
        "pt": "Alto",
        "tr": "Yüksek",
        "hu": "Magas",
        "pl": "Wysoki",
        "ro": "Ridicat",
        "sk": "Vysoký",
        "th": "สูง",
        "vi": "Cao",
        "ko": "표준이상",
        "jp": "高い",
        "rus": "Высокий",
        "csy": "Vysoký",
        "zh_CN": "偏高",
        "zh_TW": "偏高",
        "fa": "Haute",
    },
    "insufficient": {
        "en": "Inadequate",
        "nl": "Ontoereikend",
        "de": "Unzureichend",
        "es": "inadecuado",
        "it": "Inadeguato",
        "ar": "غير كافي",
        "pt": "Inadequado",
        "tr": "Yetersiz",
        "hu": "Nem megfelelő",
        "pl": "Niewystarczający",
        "ro": "Inadecvat",
        "sk": "Nedostatok",
        "th": "ไม่เพียงพอ",
        "vi": "Không đủ",
        "ko": "부적절한",
        "jp": "不十分",
        "rus": "Недопустимо",
        "csy": "Nedostatek",
        "zh_CN": "不足",
        "zh_TW": "不足",
        "fa": "Insuffisant",
    },
    "low": {
        "en": "Low",
        "nl": "Laag",
        "de": "Niedrig",
        "es": "Bajo",
        "it": "Basso",
        "ar": "منخفض",
        "pt": "Baixo",
        "tr": "Düşük",
        "hu": "Alacsony",
        "pl": "Niski",
        "ro": "Scăzut",
        "sk": "Nízky",
        "th": "ต่ำ",
        "vi": "Thấp",
        "ko": "표준이하",
        "jp": "低い",
        "rus": "Низкий",
        "csy": "Nízký",
        "zh_CN": "偏低",
        "zh_TW": "偏低",
        "fa": "Faible",
    },
    "normal": {
        "en": "Normal",
        "nl": "Normaal",
        "de": "Normal",
        "es": "Normal",
        "it": "Normale",
        "ar": "عادي",
        "pt": "Normal",
        "tr": "Normal",
        "hu": "Normál",
        "pl": "Prawidłowa waga",
        "ro": "Normal",
        "sk": "Štandardné",
        "th": "มาตรฐาน",
        "vi": " Bình thường",
        "ko": "정상체중",
        "jp": "正常",
        "rus": "Нормальный вес",
        "csy": "Normální",
        "zh_CN": "正常",
        "zh_TW": "正常",
        "fa": "Ordinaire",
    },
    "not_standard": {
        "en": "Standard Not Met",
        "nl": "Standaard niet gehaald",
        "de": "Standard nicht erfüllt",
        "es": "insuficiente",
        "it": "Insufficiente",
        "ar": "لا يلبي المعايير",
        "pt": "Não conseguir o padrão",
        "tr": "Standardı Karşılamıyor",
        "hu": "Átlag nincs elérve",
        "pl": "Nie spełnia standardów",
        "ro": "Nu corespunde standardului",
        "sk": "Nespĺňa štandard",
        "th": "ต่ำกว่ามาตรฐาน",
        "vi": "Không đủ",
        "ko": "표준치 미달",
        "jp": "基準を満たしていない",
        "rus": "Недостаточно",
        "csy": "Nesplňuje standard",
        "zh_CN": "不达标",
        "zh_TW": "不達標",
        "fa": "Non conforme à la norme",
    },
    "obesity": {
        "en": "Obesity",
        "nl": "Obese",
        "de": "Adipositas",
        "es": "Obesidad",
        "it": "Obesità ",
        "ar": "بدانة",
        "pt": "Obesidade",
        "tr": "Obezite",
        "hu": "Elhízottság",
        "pl": "Otyłość",
        "ro": "Obezitatea",
        "sk": "Obezita",
        "th": "โรคอ้วน",
        "vi": " Béo phì",
        "ko": "비만",
        "jp": "肥満",
        "rus": "Ожирение",
        "csy": "Obezita",
        "zh_CN": "肥胖",
        "zh_TW": "肥胖",
        "fa": "Obésité",
    },
    "overweight": {
        "en": "Overweight",
        "nl": "Overgewicht",
        "de": "Übergewicht",
        "es": "Sobrepeso",
        "it": "Sovrappeso",
        "ar": "زيادة الوزن",
        "pt": "Excesso de peso",
        "tr": "Yüksek",
        "hu": "Túlsúly",
        "pl": "Nadwaga",
        "ro": "Supraponderal",
        "sk": "Nadváha",
        "th": "น้ำหนักเกิน",
        "vi": " Thừa cân",
        "ko": "과체중",
        "jp": "太りすぎ",
        "rus": "Избыточная масса тела",
        "csy": "Nadváha",
        "zh_CN": "超重",
        "zh_TW": "超重",
        "fa": "Surpoids",
    },
    "standard": {
        "en": "Standard",
        "nl": "Standaard",
        "de": "Standard",
        "es": "Cumplida",
        "it": "Soddisfa gli standard",
        "ar": "يلبي المعايير",
        "pt": "Conseguir o padrão",
        "tr": "Standart",
        "hu": "Átlag elérve",
        "pl": "Standardowy",
        "ro": "Corespunde Standardului",
        "sk": "Spĺňa štandard",
        "th": "อยู่ในระดับมาตรฐาน",
        "vi": "Đạt tiêu chuẩn",
        "ko": "표준",
        "jp": "基準を満たす",
        "rus": "Стандартный",
        "csy": "Splňuje standard",
        "zh_CN": "达标",
        "zh_TW": "達標",
        "fa": "Conforme à la norme",
    },
    "underweight": {
        "en": "Underweight",
        "nl": "Ondergewicht",
        "de": "Untergewicht",
        "es": "Bajo de peso",
        "it": "Sottopeso",
        "ar": "نقص الوزن",
        "pt": "Abaixo do peso",
        "tr": "Zayıf",
        "hu": "Alsúlyú",
        "pl": "Niedowaga",
        "ro": "Subponderalitate",
        "sk": "Podváha",
        "th": "น้ำหนักต่ำกว่าเกณฑ์",
        "vi": " Thiếu cân",
        "ko": "측정량 부족",
        "jp": "アンダーウェイト",
        "rus": "Дефицит массы тела",
        "csy": "Podváha",
        "zh_CN": "重量不足",
        "zh_TW": "重量不足",
        "fa": "Poids insuffisant",
    },
}

# The exact official FITAGE metric titles bundled in fitage-card.js's
# METRIC_LABELS, keyed by the card's own internal METRICS key, for all 21
# supported languages. Six Dutch values are deliberately overridden from the
# literal official app text (see the matching comment above METRIC_LABELS in
# fitage-card.js for why): protein, protein_mass, bmr, fat_free_weight,
# body_fat_mass, body_water_mass.
EXPECTED_METRIC_LABELS = {
    "weight": {
        "en": "Weight",
        "nl": "Gewicht",
        "de": "Gewicht",
        "es": "Peso",
        "it": "Peso",
        "ar": "الوزن",
        "pt": "Peso",
        "tr": "Ağırlık",
        "hu": "Súly",
        "pl": "Waga",
        "ro": "Greutate",
        "sk": "Hmotnosť",
        "th": "น้ำหนัก",
        "vi": " Cân nặng",
        "ko": "체중",
        "jp": "体重",
        "rus": "Вес",
        "csy": "Hmotnost",
        "zh_CN": "体重",
        "zh_TW": "體重",
        "fa": "Poids",
    },
    "bmi": {
        "en": "BMI",
        "nl": "BMI",
        "de": "BMI",
        "es": "IMC",
        "it": "BMI",
        "ar": "مؤشر كتلة الجسم",
        "pt": "BMI",
        "tr": "VKİ",
        "hu": "BMI",
        "pl": "BMI",
        "ro": "IMC",
        "sk": "BMI",
        "th": "ดัชนีมวลกาย",
        "vi": "Chỉ số khối cơ thể",
        "ko": "BMI",
        "jp": "BMI",
        "rus": "Индекс массы тела",
        "csy": "BMI",
        "zh_CN": "BMI",
        "zh_TW": "BMI",
        "fa": "IMC",
    },
    "bodyfat": {
        "en": "Body fat",
        "nl": "Lichaamsvet",
        "de": "Körperfett",
        "es": "Grasa corporal",
        "it": "Grasso corporeo",
        "ar": "دهون الجسم",
        "pt": "Gordura corporal",
        "tr": "Vücut Yağ Oranı ",
        "hu": "Testzsír",
        "pl": "Tłuszcz ciała",
        "ro": "Grăsime corp.",
        "sk": "Telesný tuk",
        "th": "ไขมัน",
        "vi": "Lượng mỡ cơ thể",
        "ko": "체내 지방율",
        "jp": "体脂肪率",
        "rus": "Содержание жира",
        "csy": "Tělesný tuk",
        "zh_CN": "脂肪率",
        "zh_TW": "脂肪率",
        "fa": "Graisse corporelle",
    },
    "water": {
        "en": "Body water",
        "nl": "Lichaamswater",
        "de": "Körperwasser",
        "es": "Agua corporal",
        "it": "Idratazione",
        "ar": "مياه الجسم",
        "pt": "Lìquido corporal",
        "tr": "Vücut Suyu",
        "hu": "Test Víz",
        "pl": "Zawartość wody w organiźmie",
        "ro": "Nivel hidratare",
        "sk": "Telesná voda",
        "th": "น้ำในร่างกาย",
        "vi": " Lượng nước cơ thể",
        "ko": "체내 수분",
        "jp": "体水分率",
        "rus": "Содержание воды в организме",
        "csy": "Tělesná voda",
        "zh_CN": "体水份",
        "zh_TW": "體水份",
        "fa": "Eau Corporelle Totale",
    },
    "muscle": {
        "en": "Muscle Mass Percentage",
        "nl": "Spierverhouding",
        "de": "Muskelanteil",
        "es": "Índice de Masa Muscular",
        "it": "Rapporto muscolare",
        "ar": "معدل العضلات",
        "pt": "Proporção muscular",
        "tr": "Kas oranı",
        "hu": "Izom arány",
        "pl": "Stosunek mięśniowy",
        "ro": "Rata musculară",
        "sk": "Pomer svalov",
        "th": "อัตราส่วนกล้ามเนื้อ",
        "vi": "Tỷ lệ cơ bắp",
        "ko": "근육 비율",
        "jp": "筋肉比率",
        "rus": "Мышечное соотношение",
        "csy": "svalový poměr",
        "zh_CN": "肌肉率",
        "zh_TW": "肌肉率",
        "fa": "Ratio musculaire",
    },
    "protein": {
        "en": "Protein",
        "nl": "Eiwit",
        "de": "Protein",
        "es": "Proteína",
        "it": "Proteine",
        "ar": "بروتين",
        "pt": "Proteína",
        "tr": "Protein",
        "hu": "Protein",
        "pl": "Białko",
        "ro": "Proteină",
        "sk": "Proteín",
        "th": "โปรตีน",
        "vi": "Protein",
        "ko": "단백질",
        "jp": "タンパク質",
        "rus": "Белки",
        "csy": "Protein",
        "zh_CN": "蛋白质",
        "zh_TW": "蛋白質",
        "fa": "Protéine",
    },
    "bone": {
        "en": "Bone Mass",
        "nl": "Botmassa",
        "de": "Knochenmasse",
        "es": "Masa ósea",
        "it": "Massa ossea",
        "ar": "كتلة العظام",
        "pt": "Massa óssea",
        "tr": "Kemik Kütlesi",
        "hu": "Csont tömeg",
        "pl": "Masa kości",
        "ro": "Masă osoasă",
        "sk": "Kostná hmota",
        "th": "มวลกระดูก",
        "vi": " Khối lượng xương",
        "ko": "골격(뼈)량",
        "jp": "骨量",
        "rus": "Костная масса",
        "csy": "Kostní hmota",
        "zh_CN": "骨量",
        "zh_TW": "骨量",
        "fa": "Masse osseuse",
    },
    "subfat": {
        "en": "Subcutaneous fat",
        "nl": "Onderhuids vet",
        "de": "Subkutanes Fett",
        "es": "Índice de grasa subcutánea",
        "it": "Grasso sottocutaneo",
        "ar": "دهون تحت الجلد",
        "pt": "Gordura subcutânea",
        "tr": "Deri Altı Yağ Oranı",
        "hu": "Szubkután zsír",
        "pl": "Tłuszcz podskórny",
        "ro": "Grăsime subcutanată",
        "sk": "Podkožný tuk",
        "th": "ไขมันใต้ผิวหนัง",
        "vi": " Mỡ dưới da",
        "ko": "피하 지방",
        "jp": "皮下脂肪",
        "rus": "Подкожно-жировая клетчатка",
        "csy": "Podkožní tuk",
        "zh_CN": "皮下脂肪率",
        "zh_TW": "皮下脂肪",
        "fa": "Graisse sous-cutanée",
    },
    "fat_free_weight": {
        "en": "Fat-Free Body Weight",
        "nl": "Vetvrij gewicht",
        "de": "Fettfreie Masse",
        "es": "Peso sin grasa",
        "it": "Peso corporeo senza grassi",
        "ar": "وزن الجسم بدون دهون",
        "pt": "Peso corporal sem gordura",
        "tr": "Yağsız Vücut Ağırlığı",
        "hu": "Zsírmentes testsúly",
        "pl": "Masa ciała bez tłuszczu",
        "ro": "Greutate corporală fără grăsime",
        "sk": "Hmotnosť bez tuku",
        "th": "มวลร่างกายไร้ไขมัน",
        "vi": " Trọng lượng cơ thể không béo",
        "ko": "총지방 제거 체중",
        "jp": "除脂肪体重",
        "rus": "Масса тела без учета жира",
        "csy": "Hmotnost bez tuku",
        "zh_CN": "去脂体重",
        "zh_TW": "去脂體重",
        "fa": "Poids hors masse grasse",
    },
    "body_fat_mass": {
        "en": "Fat mass",
        "nl": "Vetmassa",
        "de": "Körperfettmasse",
        "es": "Masa grasa corporal",
        "it": "Massa grassa corporea",
        "ar": "كتلة الدهون في الجسم",
        "pt": "Massa gorda corporal",
        "tr": "Vücut Yağ Kitlesi",
        "hu": "Testzsír tömege",
        "pl": "Masa tłuszczu ciała",
        "ro": "Masă grasă corporală",
        "sk": "Hmotnosť telesného tuku",
        "th": "มวลไขมันในร่างกาย",
        "vi": "Khối lượng mỡ trong cơ thể",
        "ko": "체내 지방량",
        "jp": "体脂肪量",
        "rus": "Масса жира в теле",
        "csy": "Tělesná tuková hmota",
        "zh_CN": "体脂肪量",
        "zh_TW": "體脂肪量",
        "fa": "Masse grasse corporelle",
    },
    "body_water_mass": {
        "en": "Body Water Mass",
        "nl": "Watermassa",
        "de": "Wassermasse im Körper",
        "es": "Masa de agua corporal",
        "it": "Massa d'acqua corporea",
        "ar": "محتوى الماء في الجسم",
        "pt": "Massa de água corporal",
        "tr": "Vücut Su Kütlesi",
        "hu": "Testvíz tömege",
        "pl": "Masa wody w ciele",
        "ro": "Masă de apă în corp",
        "sk": "Hmotnosť vody v tele",
        "th": "มวลน้ำในร่างกาย",
        "vi": "Khối lượng nước trong cơ thể",
        "ko": "체내 수분량",
        "jp": "体水分量",
        "rus": "Масса воды в теле",
        "csy": "Obsah vody v těle",
        "zh_CN": "体水分量",
        "zh_TW": "體水分量",
        "fa": "Masse d'eau corporelle",
    },
    "protein_mass": {
        "en": "Protein Mass",
        "nl": "Eiwitmassa",
        "de": "Proteinmasse",
        "es": "Masa de proteínas",
        "it": "Massa proteica",
        "ar": "كتلة البروتين",
        "pt": "Massa de proteína",
        "tr": "Protein kütle",
        "hu": "Fehérjemennyiség",
        "pl": "Masa białka",
        "ro": "Masă de proteine",
        "sk": "Hmotnosť bielkovín",
        "th": "มวลโปรตีน",
        "vi": "Khối lượng protein",
        "ko": "단백질 질량",
        "jp": "タンパク質量",
        "rus": "Масса белка",
        "csy": "Hmotnost bílkovin",
        "zh_CN": "蛋白质质量",
        "zh_TW": "蛋白質質量",
        "fa": "Masse protéique",
    },
    "bmr": {
        "en": "BMR",
        "nl": "Basaal metabolisme",
        "de": "Grundumsatz",
        "es": "TMB",
        "it": "BMR",
        "ar": "معدل الأيض الأساسي",
        "pt": "BMR",
        "tr": "Bazal Metabolizma Hızı",
        "hu": "BMR",
        "pl": "BMR (podstawowa przemiana materii)",
        "ro": "RMB",
        "sk": "BMR",
        "th": "อัตราการเผาผลาญขณะพัก",
        "vi": " BMR",
        "ko": "기초대사량",
        "jp": "基礎代謝量",
        "rus": "Скорость обмена веществ",
        "csy": "BMR",
        "zh_CN": "基础代谢量",
        "zh_TW": "基礎代謝量",
        "fa": "Taux métab. debase",
    },
    "score": {
        "en": "Health Score",
        "nl": "Gezondheidsscore",
        "de": "Gesundheitspunktzahl",
        "es": "Puntuación de salud",
        "it": "Punteggio di salute",
        "ar": "نقاط الصحة",
        "pt": "Pontuação de saúde",
        "tr": "Sağlık Skoru",
        "hu": "Egészségpontszám",
        "pl": "Wynik zdrowia",
        "ro": "Scor de sănătate",
        "sk": "Skóre zdravia",
        "th": "คะแนนสุขภาพ",
        "vi": "Điểm sức khỏe",
        "ko": "건강 점수",
        "jp": "健康スコア",
        "rus": "Оценка здоровья",
        "csy": "Zdravotní skóre",
        "zh_CN": "健康分数",
        "zh_TW": "健康分數",
        "fa": "Score de santé",
    },
}

# The official FITAGE translation key "current" (proven present and
# non-empty in all 21 supported languages, with the appSpecialTranslation
# override applied for English), used for the "current value" label - with
# one deliberate exception: Thai ("th") is intentionally left out. The
# official Thai string for this key, "กระแสน้ำ", means "water current"/
# "tide", not "current value", and would mislabel every metric's present-day
# reading. "th" must therefore fall through to the English fallback
# ("Current") instead of ever carrying an entry here; see
# EXPECTED_CURRENT_LABEL_FALLBACK_LANGUAGES below and the matching comment
# on CURRENT_LABELS in fitage-card.js.
EXPECTED_CURRENT_LABELS = {
    "en": "Current",
    "nl": "Huidig",
    "de": "Aktuell",
    "es": "Actual",
    "it": "Attuale",
    "ar": "حالي",
    "pt": "Atual",
    "tr": "Güncel",
    "hu": "aktuális",
    "pl": "Aktualnie",
    "ro": "curent",
    "sk": "aktuálny",
    "vi": "Hiện tại",
    "ko": "현재",
    "jp": "現在",
    "rus": "Текущий",
    "csy": "aktuální",
    "zh_CN": "当前",
    "zh_TW": "當前",
    "fa": "En cours",
}

# Languages that must NOT have their own CURRENT_LABELS entry and must fall
# back to the English "Current" - currently only Thai, due to its official
# app text being a false friend ("water current", not "current value").
EXPECTED_CURRENT_LABEL_FALLBACK_LANGUAGES = {"th"}


def _find_node() -> str | None:
    """Locate a Node.js runtime for real JS-behavior tests. Falls back to
    the editor-bundled binary in this dev container when `node` is not on
    PATH; tests using this skip gracefully if neither is found."""
    if node := shutil.which("node"):
        return node
    for candidate in Path("/vscode/vscode-server/bin").glob("linux-x64/*/node"):
        if candidate.is_file():
            return str(candidate)
    return None


NODE_BIN = _find_node()


def _run_node_js(harness: str, **js_consts: object) -> subprocess.CompletedProcess:
    """Run a Node.js harness with CARD_PATH (and any extra JS consts) defined
    ahead of it, so tests can drive the real bundled card under Node instead
    of only pattern-matching its source text."""
    prelude = f"const CARD_PATH = {json.dumps(str(CARD_PATH))};\n"
    for name, value in js_consts.items():
        prelude += f"const {name} = {json.dumps(value)};\n"
    return subprocess.run(
        [NODE_BIN, "-e", prelude + harness],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


_LOAD_CARD_JS_PRELUDE = r"""
class FakeElement {
  attachShadow() { this.shadowRoot = { innerHTML: "", querySelector: () => null, querySelectorAll: () => [] }; return this.shadowRoot; }
}
global.HTMLElement = FakeElement;
global.customElements = { registry: new Map(), get(n){return this.registry.get(n)}, define(n,c){this.registry.set(n,c)} };
global.window = { customCards: undefined, loadCardHelpers: async () => ({ createCardElement: () => ({}) }) };
global.document = { createElement: () => ({}) };

const fs = require("fs");
const src = fs.readFileSync(CARD_PATH, "utf8");
eval(src);

const Card = customElements.get("fitage-card");
"""

_STUB_HINT_JS_HARNESS = (
    _LOAD_CARD_JS_PRELUDE
    + r"""
async function run(profile, hass) {
  const el = Object.create(Card.prototype);
  el.attachShadow = FakeElement.prototype.attachShadow;
  el.attachShadow();
  el.range = "1m"; el.graphs = new Map(); el.latest = new Map(); el.graphGeneration = 0;
  el.setConfig({ profile });
  el._hass = hass;
  await el.initialize();
  return { error: el.error, hint: el.hint };
}

(async () => {
  const hassEmpty = { callWS: async ({type}) => type === "recorder/list_statistic_ids" ? [] : {}, states: {} };

  const stub = await run("jouw_profiel", hassEmpty);
  if (stub.error) throw new Error("stub profile must not set this.error: " + stub.error);
  if (stub.hint !== "Kies een FITAGE-profiel in de kaarteditor.") throw new Error("stub profile must set the neutral hint, got: " + stub.hint);

  const invalid = await run("een_niet_bestaand_profiel", hassEmpty);
  if (!invalid.error) throw new Error("a real but invalid profile must still set this.error");
  if (invalid.hint) throw new Error("a real but invalid profile must not set the neutral hint");

  console.log("ALL JS BEHAVIOR CHECKS PASSED");
})().catch(e => { console.error(e); process.exit(1); });
"""
)

_FORMAT_JS_HARNESS = (
    _LOAD_CARD_JS_PRELUDE
    + r"""
const cases = CASES;
// format() now reads hass.locale (Dutch number formatting is no longer a
// fixed "nl-NL" default) - bind the same Dutch locale these pre-existing
// cases were always written against, so their expected output is unchanged.
const dutchHass = { locale: { language: "nl", number_format: "language" } };
const failures = [];
for (const [value, unit, key, expected] of cases) {
  const actual = Card.prototype.format.call({ _hass: dutchHass }, value, unit, key);
  if (actual !== expected) {
    failures.push(`format(${JSON.stringify(value)}, ${JSON.stringify(unit)}, ${JSON.stringify(key)}) = ${JSON.stringify(actual)}, expected ${JSON.stringify(expected)}`);
  }
}
if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}
console.log("ALL FORMAT CHECKS PASSED");
"""
)

_FIND_PREFIX_JS_HARNESS = (
    _LOAD_CARD_JS_PRELUDE
    + r"""
function makeEl(slug, states, statsById) {
  const el = Object.create(Card.prototype);
  el.slug = slug;
  el.config = {};
  el._hass = {
    states: states || {},
    callWS: async ({ type, statistic_ids }) => {
      if (type !== "recorder/statistics_during_period") return {};
      const out = {};
      for (const id of statistic_ids) out[id] = (statsById || {})[id] || [];
      return out;
    },
  };
  return el;
}

(async () => {
  // 1) Structural fix: "fitage:aaa_fat_free_weight" must never be mistaken
  // for a weight statistic just because it also ends in "_weight".
  {
    const el = makeEl("profiel_een", {});
    const prefix = await el.findPrefix(["fitage:aaa_weight", "fitage:aaa_fat_free_weight"], []);
    if (prefix !== "fitage:aaa") throw new Error("check 1: expected fitage:aaa, got " + prefix);
  }

  // 2) Reliable statistic metadata (the display name our own backend writes
  // in statistics.py) resolves the right profile deterministically, with no
  // value comparison involved at all.
  {
    const el = makeEl("piet", {});
    const metadata = [
      { statistic_id: "fitage:h1_weight", name: "FITAGE Jan – Weight" },
      { statistic_id: "fitage:h2_weight", name: "FITAGE Piet – Weight" },
    ];
    const prefix = await el.findPrefix(["fitage:h1_weight", "fitage:h2_weight"], metadata);
    if (prefix !== "fitage:h2") throw new Error("check 2: expected fitage:h2, got " + prefix);
  }

  // 3) Two profiles whose display names collide (the "(<hex>)" disambiguation
  // suffix statistics.py appends stripped back off) must never be guessed
  // between, even with metadata present.
  {
    const el = makeEl("jan", {});
    const metadata = [
      { statistic_id: "fitage:h1_weight", name: "FITAGE Jan (a1b2) – Weight" },
      { statistic_id: "fitage:h2_weight", name: "FITAGE Jan (a1b3) – Weight" },
    ];
    const prefix = await el.findPrefix(["fitage:h1_weight", "fitage:h2_weight"], metadata);
    if (prefix !== null) throw new Error("check 3: expected null for a colliding display name, got " + prefix);
  }

  // 4) Without usable metadata, a single unambiguously close value candidate
  // still resolves - the pre-existing fallback behavior stays intact.
  {
    const el = makeEl("profiel_een", { "sensor.profiel_een_weight": { state: "80.0" } }, {
      "fitage:h1_weight": [{ state: "80.05" }],
      "fitage:h2_weight": [{ state: "95.0" }],
    });
    const prefix = await el.findPrefix(["fitage:h1_weight", "fitage:h2_weight"], []);
    if (prefix !== "fitage:h1") throw new Error("check 4: expected fitage:h1, got " + prefix);
  }

  // 5) Two candidates equally close to the live value must never be guessed
  // between - the multi-profile ambiguity this whole fix is about.
  {
    const el = makeEl("profiel_een", { "sensor.profiel_een_weight": { state: "80.0" } }, {
      "fitage:h1_weight": [{ state: "80.05" }],
      "fitage:h2_weight": [{ state: "80.06" }],
    });
    const prefix = await el.findPrefix(["fitage:h1_weight", "fitage:h2_weight"], []);
    if (prefix !== null) throw new Error("check 5: expected null for two equally plausible candidates, got " + prefix);
  }

  console.log("ALL FIND-PREFIX CHECKS PASSED");
})().catch((e) => { console.error(e.stack || e); process.exit(1); });
"""
)

_ASSESSMENT_JS_HARNESS = (
    _LOAD_CARD_JS_PRELUDE
    + r"""
const WEIGHT_METRIC = { key: "weight", title: "Gewicht", entity: "weight", unit: "kg" };

function stateWithAssessment(assessment) {
  const attributes = { normal_min: 60, normal_max: 90, unit_of_measurement: "kg" };
  if (assessment !== undefined) attributes.assessment = assessment;
  return { state: "80", attributes };
}

function makeMetricCard(hass, config) {
  const el = Object.create(Card.prototype);
  el.config = { title: "FITAGE", display: "graphs", ...(config || {}) };
  el.slug = "test_profiel";
  el._hass = hass;
  return el;
}

function renderCurrentCell(assessment, hass, config) {
  const el = makeMetricCard(
    hass || { states: { "sensor.test_profiel_weight": stateWithAssessment(assessment) }, language: "nl" },
    config
  );
  return el.metricHtml(WEIGHT_METRIC);
}

const failures = [];
function check(label, condition) {
  if (!condition) failures.push(label);
}

// 1) Official color mapping, verified through the real bundled metricHtml(),
// not by re-reading the LEVEL_COLORS object directly - this proves the
// lookup is actually wired into the rendered "Actueel" value.
const COLOR_CASES = [
  ["normal", "#46C083"],
  ["average", "#46C083"],
  ["low", "#3A9BE6"],
  ["below_average", "#3A9BE6"],
  ["high", "#E3B026"],
  ["above_average", "#E3B026"],
  ["excellent", "#7FC534"], // must be light green, never amber
  ["fitness", "#7FC534"],
  ["acceptable", "#60BD36"],
  ["obesity", "#DE7A38"], // dark orange
  ["excessive", "#DE7A38"], // dark orange
  ["not_standard", "#3A9BE6"], // bmr: below the official reference
  ["standard", "#46C083"], // bmr: at or above the official reference
];
for (const [assessment, hex] of COLOR_CASES) {
  const html = renderCurrentCell(assessment);
  check(
    `color for "${assessment}" must be ${hex}`,
    html.includes(`id="current-weight" class="current" style="color:${hex}"`)
  );
}

// 2) Dutch labels (hass.language: "nl").
const NL_LABEL_CASES = [
  ["normal", "Normaal"],
  ["below_average", "Ondergemiddeld"],
  ["above_average", "Bovengemiddeld"],
  ["essential_fat", "Essentieel Vet"],
  ["not_standard", "Standaard niet gehaald"],
  ["standard", "Standaard"],
];
for (const [assessment, text] of NL_LABEL_CASES) {
  const html = renderCurrentCell(assessment);
  check(`Dutch label for "${assessment}" must show "${text}"`, html.includes(`>${text}<`));
}

// 3) English fallback labels (hass.language: "en"), including the official,
// effective (override-merged) "excellent" -> "Excellent" text - not the raw,
// unmerged translation/en.json text ("Adequate"), which the real app never
// actually shows, proven via its own appSpecialTranslation data.
const EN_LABEL_CASES = [
  ["normal", "Normal"],
  ["excellent", "Excellent"],
  ["below_average", "Below average"],
  // official, effective (override-merged) text - not the raw, unmerged
  // translation/en.json text ("Insufficient"/"Sufficient").
  ["not_standard", "Standard Not Met"],
  ["standard", "Standard"],
];
for (const [assessment, text] of EN_LABEL_CASES) {
  const html = renderCurrentCell(assessment, {
    states: { "sensor.test_profiel_weight": stateWithAssessment(assessment) },
    language: "en",
  });
  check(`English label for "${assessment}" must show "${text}"`, html.includes(`>${text}<`));
}

// 4) Missing assessment attribute: exact current orange fallback, no label.
{
  const html = renderCurrentCell(undefined);
  check(
    "missing assessment must not set an inline current color",
    !/id="current-weight" class="current" style=/.test(html)
  );
  check(
    "missing assessment must render the assessment element hidden and empty",
    html.includes('id="assessment-weight" class="assessment" hidden></small>')
  );
}

// 5) Unknown assessment key: same exact fallback, never a fabricated label.
{
  const html = renderCurrentCell("een_onbekende_sleutel");
  check(
    "unknown assessment must not set an inline current color",
    !/id="current-weight" class="current" style=/.test(html)
  );
  check(
    "unknown assessment must render the assessment element hidden and empty",
    html.includes('id="assessment-weight" class="assessment" hidden></small>')
  );
}

// 6) An explicit, valid manual current_color always wins over the official
// per-category color, even when the assessment is a known, colored key.
{
  const config = { custom_colors: true, current_color: "#123456" };
  const html = renderCurrentCell("normal", undefined, config);
  check(
    "a manual current_color must suppress the inline official color",
    !/id="current-weight" class="current" style=/.test(html)
  );
  const el = makeMetricCard({ states: {}, language: "nl" }, config);
  check(
    "the manual current_color must still reach --fitage-current-color",
    el.appearance().includes("--fitage-current-color:#123456;")
  );
}

if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}
console.log("ALL ASSESSMENT CHECKS PASSED");
"""
)

# Reproduces, in isolation, the exact Home Assistant lazy-loading race that
# caused "TypeError: Cannot read properties of undefined (reading 'config')"
# in hui-graph-header-footer's _subscribeHistory(): per Home Assistant's own
# src/panels/lovelace/create-element/create-element-base.ts (_lazyCreate),
# createCardElement() for a not-yet-loaded card type returns an unconfigured
# element synchronously and only calls customElements.upgrade(element) then
# element.setConfig(config) later, inside a .then() on
# customElements.whenDefined(tag). A first fix (awaiting that promise before
# ever *attaching* the element to the DOM) was not enough: setting a
# property such as .hass on the still-un-upgraded element in the meantime
# creates a plain own data property; verified against the real, locally
# installed home-assistant-frontend in an actual Chromium build, upgrading
# such an element deletes that shadowing own property but does *not* replay
# its value through the real accessor - the assigned value is silently
# lost, .hass reads back as undefined, and any nested element that reads
# this.hass.config throws exactly the reported TypeError. This harness
# implements just enough of customElements/DOM (FakeRegistry/FakeContainer,
# with a real GraphCard constructor/prototype so property lookup exhibits
# the actual own-property-shadows-prototype-accessor dynamic) to reproduce
# both the upgrade-then-setConfig ordering and the hass-shadowing
# faithfully, then drives the real, bundled createGraphs()/render()/hass
# setter through it.
_GRAPH_LIFECYCLE_JS_HARNESS = r"""
const fs = require("fs");
const src = fs.readFileSync(CARD_PATH, "utf8");
class FakeContainer {
  constructor() { this.child = null; }
  replaceChildren(el) {
    if (this.child && this.child !== el) {
      this.child.__connected = false;
      if (this.child.__upgraded && typeof this.child.disconnectedCallback === "function") this.child.disconnectedCallback();
    }
    this.child = el || null;
    if (el) {
      el.__connected = true;
      if (el.__upgraded && typeof el.connectedCallback === "function") el.connectedCallback();
    }
  }
  disconnect() {
    if (this.child) {
      this.child.__connected = false;
      if (this.child.__upgraded && typeof this.child.disconnectedCallback === "function") this.child.disconnectedCallback();
    }
  }
}
class FakeRegistry {
  constructor() { this.factories = new Map(); this.waiters = new Map(); }
  define(tag, value) {
    this.factories.set(tag, value);
    const list = this.waiters.get(tag);
    if (list) { this.waiters.delete(tag); list.forEach((resolve) => resolve()); }
  }
  get(tag) { return this.factories.get(tag); }
  whenDefined(tag) {
    if (this.factories.has(tag)) return Promise.resolve();
    return new Promise((resolve) => {
      const list = this.waiters.get(tag) || [];
      list.push(resolve);
      this.waiters.set(tag, list);
    });
  }
  upgrade(el) {
    const Ctor = this.factories.get(el.__tag);
    if (!Ctor || el.__upgraded || !Ctor.__isLovelaceStub) return;
    upgradeElement(el, Ctor);
    el.__upgraded = true;
    if (el.__connected && typeof el.connectedCallback === "function") el.connectedCallback();
  }
}
const registry = new FakeRegistry();
global.customElements = registry;
const GRAPH_CARD_TAG = "hui-statistics-graph-card";
const violations = [];
// A real constructor + prototype (not per-instance methods) so property
// lookup exhibits the actual own-property-shadows-prototype-accessor
// dynamic this whole fix is about, and `instanceof` behaves like it does
// for a real, defined custom element class. hassSetterCalls only
// increments when an assignment genuinely reaches this accessor - the
// decisive signal a plain instance-property shadow was never used.
let hassSetterCalls = 0;
class GraphCard {
  setConfig(cfg) { this._config = cfg; }
  connectedCallback() {
    if (this._config === undefined) violations.push("connectedCallback fired with _config still undefined");
    if (this.hass === undefined) violations.push("connectedCallback fired with hass still undefined");
  }
  disconnectedCallback() {}
}
GraphCard.__isLovelaceStub = true;
Object.defineProperty(GraphCard.prototype, "hass", {
  configurable: true,
  get() { return this.__hassValue; },
  set(v) { hassSetterCalls += 1; this.__hassValue = v; },
});
function upgradeElement(el, Ctor) {
  // Verified against the real, locally installed home-assistant-frontend in
  // an actual Chromium build: upgrading an element whose "hass" was set
  // beforehand (an own data property, since no accessor existed yet)
  // deletes that shadowing own property, but does *not* replay its value
  // through the real accessor - the assigned value is silently lost, and
  // .hass reads back as undefined afterwards. Reproduced faithfully here.
  if (Object.hasOwn(el, "hass")) delete el.hass;
  Object.setPrototypeOf(el, Ctor.prototype);
}
global.document = {
  createElement(tag) {
    const el = { __tag: tag, __upgraded: false, __connected: false };
    const Ctor = registry.get(tag);
    if (Ctor && Ctor.__isLovelaceStub) { upgradeElement(el, Ctor); el.__upgraded = true; }
    return el;
  },
};
let createCount = 0;
const createWaiters = [];
function waitForCreateCount(n) {
  if (createCount >= n) return Promise.resolve();
  return new Promise((resolve) => createWaiters.push({ n, resolve }));
}
function haCreateCardElement(config) {
  const tag = `hui-${config.type}-card`;
  let el;
  if (registry.get(tag)) {
    el = document.createElement(tag);
    el.setConfig(config);
  } else {
    el = document.createElement(tag);
    registry.whenDefined(tag).then(() => {
      registry.upgrade(el);
      el.setConfig(config);
    });
  }
  createCount += 1;
  for (let i = createWaiters.length - 1; i >= 0; i -= 1) {
    if (createWaiters[i].n <= createCount) { createWaiters[i].resolve(); createWaiters.splice(i, 1); }
  }
  return el;
}
global.window = { customCards: undefined, loadCardHelpers: async () => ({ createCardElement: haCreateCardElement }) };
class FakeElement {
  constructor() {
    // A newly created custom element starts out connected to the DOM in
    // these scenarios (matching Home Assistant inserting a freshly built
    // card into a dashboard/preview); scenario J flips this to false to
    // simulate removal.
    this.isConnected = true;
  }
  attachShadow() {
    const containers = new Map();
    let html = "";
    this.shadowRoot = {
      get innerHTML() { return html; },
      set innerHTML(value) { html = value; containers.forEach((c) => c.disconnect()); },
      querySelector(sel) {
        if (!containers.has(sel)) containers.set(sel, new FakeContainer());
        return containers.get(sel);
      },
      querySelectorAll: () => [],
    };
    return this.shadowRoot;
  }
}
global.HTMLElement = FakeElement;

eval(src);
const Card = customElements.get("fitage-card");

function makeCard(available) {
  const el = Object.create(Card.prototype);
  el.isConnected = true;
  el.attachShadow();
  el.range = "1m";
  el.graphs = new Map();
  el.latest = new Map();
  el.graphGeneration = 0;
  el.config = { title: "FITAGE", display: "graphs", profile: "test_profiel" };
  el.slug = "test_profiel";
  el.statisticPrefix = "fitage:test_profiel";
  el._hass = { states: {}, config: { components: [] } };
  el.ready = true;
  el.initialized = true; // a real ready:true card would already have completed initialize()
  el.available = available;
  return el;
}

const oneMetric = () => [{ key: "weight", title: "Gewicht", entity: "weight", unit: "kg" }];

function makeFreshCard() {
  // A genuinely new instance the way Home Assistant creates one - via the
  // real constructor, with neither hass nor config assigned yet - so these
  // scenarios exercise the real setConfig()/hass ordering guards, not a
  // hand-poked internal state.
  return new Card();
}
function fakeHass(profile) {
  return {
    config: { components: [] },
    states: {},
    callWS: async ({ type }) => {
      if (type === "recorder/list_statistic_ids") {
        return [{ statistic_id: `fitage:${profile}_weight` }];
      }
      return {};
    },
  };
}
// Like fakeHass(), but callWS() only resolves once `gate` resolves - lets a
// test hold initialize()'s prefix resolution open to switch the config
// (e.g. to the stub profile) while it is still in flight.
function fakeHassGated(profile, gate) {
  return {
    config: { components: [] },
    states: {},
    callWS: async ({ type }) => {
      await gate;
      if (type === "recorder/list_statistic_ids") {
        return [{ statistic_id: `fitage:${profile}_weight` }];
      }
      return {};
    },
  };
}
const STUB_PROFILE_VALUE = "jouw_profiel"; // mirrors fitage-card.js's own STUB_PROFILE constant, not reachable directly since it is scoped to the eval() below
// Test-only synchronization: lets an already-scheduled async chain
// (initialize() -> listStatistics() -> findPrefix() -> loadLatest() ->
// createGraphs() -> whenDefined()) actually settle before asserting on its
// outcome. This is purely a test-timing helper, never part of the
// production ordering guarantee itself, which relies solely on the
// setConfig()/hass two-sided gate and the generation token.
function settle() { return new Promise((resolve) => setTimeout(resolve, 20)); }

async function scenarioA_setConfigBeforeAttach() {
  const el = makeCard(oneMetric());
  const hassBefore = hassSetterCalls;
  const before = createCount;
  const p = el.createGraphs();
  await waitForCreateCount(before + 1);
  // The lazy module "finishes loading" only now - after the element was
  // already constructed but before production code has touched any
  // property on it.
  registry.define(GRAPH_CARD_TAG, GraphCard);
  await p;
  const container = el.shadowRoot.querySelector("#graph-weight");
  if (!container.child) throw new Error("scenario A: no graph element ended up attached");
  if (container.child.hass === undefined) throw new Error("scenario A: attached element has no hass");
  if (container.child.hass !== el._hass) throw new Error("scenario A: attached element's hass is not the card's real hass object");
  if (Object.hasOwn(container.child, "hass")) throw new Error("scenario A: hass is a shadowing own property, not delivered via the real accessor");
  if (hassSetterCalls === hassBefore) throw new Error("scenario A: the real hass accessor/setter was never actually invoked");
}

async function scenarioB_rerenderDuringInFlightCreateGraphs() {
  const el = makeCard(oneMetric());
  const previous = { __tag: GRAPH_CARD_TAG, __upgraded: true, _config: { entities: ["old"] }, hass: el._hass, connectedCallback(){}, disconnectedCallback(){} };
  el.graphs.set("weight", previous);
  el.render();
  const before = createCount;
  const p = el.createGraphs();
  await waitForCreateCount(before + 1);
  el.render();
  const containerDuringFlight = el.shadowRoot.querySelector("#graph-weight");
  if (containerDuringFlight.child !== previous) {
    throw new Error("scenario B: rerender while a new generation is in flight did not keep the previous, fully configured element");
  }
  registry.define(GRAPH_CARD_TAG, GraphCard);
  await p;
}

async function scenarioC_compactSwitchIsSafe() {
  const el = makeCard(oneMetric());
  el.config.display = "compact";
  await el.createGraphs();
  if (el.graphs.size !== 0) throw new Error("scenario C: compact mode must not create graph elements");
  el.config.display = "graphs";
  registry.define(GRAPH_CARD_TAG, GraphCard);
  await el.createGraphs();
  if (!el.graphs.get("weight")) throw new Error("scenario C: switching back to graphs mode must create the graph element");
}

async function scenarioD_periodSwitchIsSafe() {
  registry.define(GRAPH_CARD_TAG, GraphCard);
  const el = makeCard(oneMetric());
  el.range = "7d";
  const p1 = el.createGraphs();
  el.range = "1m";
  const p2 = el.createGraphs();
  await Promise.all([p1, p2]);
  const container = el.shadowRoot.querySelector("#graph-weight");
  if (!container.child || container.child.hass === undefined) {
    throw new Error("scenario D: rapid period switching must still end with a single, fully configured graph attached");
  }
  if (el.graphs.get("weight") !== container.child) {
    throw new Error("scenario D: this.graphs and the DOM disagree on which generation won");
  }
}

async function scenarioE_editorPreviewReconfigureIsSafe() {
  registry.factories.delete(GRAPH_CARD_TAG);
  const el = makeCard(oneMetric());
  const before = createCount;
  const p1 = el.createGraphs();
  await waitForCreateCount(before + 1);
  // A build is already legitimately in flight (p1); setConfig() must only
  // reconfigure and bump the generation here, not also kick off a second,
  // real initialize() cycle on top of the manual createGraphs() calls this
  // scenario is specifically about - matching how set hass()'s own guard
  // already treats "loading" as "something is already in charge of this".
  el.loading = true;
  el.setConfig({ profile: "ander_profiel" });
  el.available = oneMetric();
  // Simulate metrics for the new profile already resolved, isolating this
  // scenario to the createGraphs() overlap itself rather than re-running a
  // full initialize()/findPrefix() cycle.
  el.ready = true;
  el.statisticPrefix = "fitage:ander_profiel";
  const p2 = el.createGraphs();
  await waitForCreateCount(before + 2);
  registry.define(GRAPH_CARD_TAG, GraphCard);
  await Promise.all([p1, p2]);
  const container = el.shadowRoot.querySelector("#graph-weight");
  if (!container.child || container.child.hass === undefined) {
    throw new Error("scenario E: editor reconfigure during an in-flight createGraphs() must still end configured");
  }
}

async function scenarioF_assigningHassBeforeUpgradeIsDemonstrablyLost() {
  // Proves this harness (and thus scenario A) actually discriminates
  // correct from incorrect code: deliberately reproduce the *old*,
  // pre-fix ordering (create -> set hass -> await whenDefined) using the
  // same low-level primitives production code uses, bypassing
  // createGraphs() itself, and confirm the assignment is provably lost -
  // exactly the mechanism behind "Cannot read properties of undefined
  // (reading 'config')" in a nested element that reads this.hass.config.
  registry.factories.delete(GRAPH_CARD_TAG);
  const el = document.createElement(GRAPH_CARD_TAG);
  const hassBefore = hassSetterCalls;
  const marker = { states: {} };
  el.hass = marker; // pre-upgrade: creates a shadowing own property
  if (!Object.hasOwn(el, "hass")) {
    throw new Error("scenario F: expected a shadowing own 'hass' property before upgrade");
  }
  registry.define(GRAPH_CARD_TAG, GraphCard); // lazy module "loads" now
  registry.upgrade(el);
  el.setConfig({ entities: ["sensor.time"] });
  if (Object.hasOwn(el, "hass")) {
    throw new Error("scenario F: the shadowing own property should be gone after upgrade");
  }
  if (el.hass !== undefined) {
    throw new Error("scenario F: expected the pre-upgrade value to be lost, not delivered");
  }
  if (hassSetterCalls !== hassBefore) {
    throw new Error("scenario F: the real accessor must not have been invoked by the pre-upgrade assignment");
  }
  // A nested header/footer-style element that reads this.hass.config, the
  // same way hui-graph-header-footer.ts's _subscribeHistory() does, must
  // reproduce the exact reported TypeError when handed this undefined hass.
  let threw = null;
  try {
    void el.hass.config;
  } catch (e) {
    threw = e;
  }
  if (!(threw instanceof TypeError)) {
    throw new Error("scenario F: reading .config off the lost hass value must throw the same TypeError Home Assistant does");
  }
}

async function scenarioG_setConfigWithoutHassBuildsNothing() {
  // Mirrors Home Assistant's card-picker/editor-preview flow, which can
  // call setConfig() on a freshly created card before it ever receives a
  // hass instance.
  const el = makeFreshCard();
  const createBefore = createCount;
  el.setConfig({ profile: "order_test_profiel" });
  await settle();
  if (el.initialized) throw new Error("scenario G: setConfig() without hass must not start initialize()");
  if (createCount !== createBefore) throw new Error("scenario G: setConfig() without hass must not create any graph element");
  const container = el.shadowRoot.querySelector("#graph-weight");
  if (container.child) throw new Error("scenario G: nothing may be attached to the DOM without hass");
}

async function scenarioH_hassArrivesAfterSetConfigBuildsExactlyOnce() {
  registry.define(GRAPH_CARD_TAG, GraphCard); // already loaded: isolates the setConfig/hass order from the separate lazy-load race covered by scenario A
  const el = makeFreshCard();
  el.setConfig({ profile: "order_test_profiel" });
  const createBefore = createCount;
  const hassBefore = hassSetterCalls;
  el.hass = fakeHass("order_test_profiel"); // setConfig already ran; hass arrives second
  await settle();
  const graph = el.graphs.get("weight");
  if (!graph) throw new Error("scenario H: expected exactly one graph to have been built once hass arrived");
  if (createCount !== createBefore + 1) throw new Error("scenario H: expected exactly one graph element created, got " + (createCount - createBefore));
  if (graph.hass !== el._hass) throw new Error("scenario H: graph.hass must be the card's real hass object");
  if (!graph.hass.config) throw new Error("scenario H: graph.hass.config must exist before connectedCallback could read it");
  if (hassSetterCalls === hassBefore) throw new Error("scenario H: the real hass accessor must have been invoked");
  const container = el.shadowRoot.querySelector("#graph-weight");
  if (container.child !== graph) throw new Error("scenario H: the built graph must actually be attached to the DOM");
}

async function scenarioI_multipleSetConfigBeforeHassOnlyBuildsTheLast() {
  registry.define(GRAPH_CARD_TAG, GraphCard);
  const el = makeFreshCard();
  el.setConfig({ profile: "eerste_profiel" });
  el.setConfig({ profile: "order_test_profiel" }); // the editor changing a field again before hass ever arrived
  const createBefore = createCount;
  el.hass = fakeHass("order_test_profiel");
  await settle();
  if (createCount !== createBefore + 1) throw new Error("scenario I: only the latest config may ever be built, got " + (createCount - createBefore) + " graph element(s)");
  if (el.slug !== "order_test_profiel") throw new Error("scenario I: the card must have kept the latest config, not an earlier one");
}

async function scenarioJ_cardRemovedBeforeDeferredBuildIsNeverAttached() {
  registry.factories.delete(GRAPH_CARD_TAG); // first-time lazy load, so the build genuinely stays in flight
  const el = makeFreshCard();
  el.setConfig({ profile: "order_test_profiel" });
  el.hass = fakeHass("order_test_profiel"); // starts initialize() -> ... -> createGraphs(), still awaiting whenDefined()
  await Promise.resolve();
  el.isConnected = false; // the card has been removed from the dashboard
  registry.define(GRAPH_CARD_TAG, GraphCard); // the lazy module finishes loading only now, after removal
  await settle();
  const container = el.shadowRoot.querySelector("#graph-weight");
  if (container.child) throw new Error("scenario J: nothing may be attached once the card was removed before the deferred build finished");
}

async function scenarioL_createGraphsCalledDirectlyWithoutHassDefersAndLaterResumesOnce() {
  // Exercises createGraphs()'s own guard directly (e.g. a period button
  // click reaching selectRange() before the card is fully ready), not only
  // via the setConfig()/hass ordering scenarios above, and proves the
  // deferred build resumes exactly once - never twice - once hass arrives.
  registry.define(GRAPH_CARD_TAG, GraphCard);
  const el = makeFreshCard();
  el.config = { title: "FITAGE", display: "graphs", profile: "order_test_profiel" };
  el.slug = "order_test_profiel";
  el.statisticPrefix = "fitage:order_test_profiel";
  el.available = oneMetric();
  el.ready = true;
  // A real initialize() cycle would already have set these by the time
  // anything could call createGraphs() directly (e.g. selectRange()); set
  // them up front so this scenario isolates createGraphs()'s own
  // defer/resume guard from the separate initialize()-triggering gate in
  // set hass(), already covered by scenarios G-K above.
  el.initialized = true;
  el.lastToken = el.updateToken();
  const createBefore = createCount;
  await el.createGraphs(); // this._hass is still undefined at this point
  if (createCount !== createBefore) throw new Error("scenario L: createGraphs() must not create any element while hass is missing");
  if (el.graphsPending !== true) throw new Error("scenario L: createGraphs() must mark a build as pending when it declines to run");
  const hassSetterCallsBefore = hassSetterCalls;
  el.hass = fakeHass("order_test_profiel");
  await settle();
  const graph = el.graphs.get("weight");
  if (!graph) throw new Error("scenario L: the deferred build must resume once hass arrives");
  if (createCount !== createBefore + 1) throw new Error("scenario L: exactly one graph must have been built, got " + (createCount - createBefore));
  if (hassSetterCalls === hassSetterCallsBefore) throw new Error("scenario L: the real hass accessor must have been invoked");
  if (el.graphsPending !== false) throw new Error("scenario L: the pending flag must be cleared once the build resumed");
  // A second, unrelated hass update (same token, nothing pending anymore)
  // must not start a second, duplicate build.
  const createAfterFirstResume = createCount;
  el.hass = fakeHass("order_test_profiel");
  await settle();
  if (createCount !== createAfterFirstResume) throw new Error("scenario L: a resumed build must never be started twice");
}

async function scenarioM1_singleStubPreviewCreatesNothing() {
  registry.define(GRAPH_CARD_TAG, GraphCard);
  const el = makeFreshCard();
  const createBefore = createCount;
  el.setConfig(Card.getStubConfig());
  el.hass = fakeHass(STUB_PROFILE_VALUE);
  await settle();
  if (createCount !== createBefore) throw new Error("scenario M1: a stub preview must call createCardElement() zero times");
  if (el.graphs.size !== 0) throw new Error("scenario M1: a stub preview must attach zero graphs");
  if (el.hint !== "Kies een FITAGE-profiel in de kaarteditor.") throw new Error("scenario M1: the stub hint must be shown");
}

async function scenarioM2_twoSimultaneousStubPreviewsCreateNothing() {
  registry.define(GRAPH_CARD_TAG, GraphCard);
  const elA = makeFreshCard();
  const elB = makeFreshCard();
  const createBefore = createCount;
  elA.setConfig(Card.getStubConfig());
  elB.setConfig(Card.getStubConfig());
  const hass = fakeHass(STUB_PROFILE_VALUE);
  elA.hass = hass;
  elB.hass = hass;
  await settle();
  if (createCount !== createBefore) throw new Error("scenario M2: two simultaneous stub previews must call createCardElement() zero times combined");
  if (elA.graphs.size !== 0 || elB.graphs.size !== 0) throw new Error("scenario M2: neither simultaneous stub preview may attach a graph");
}

async function scenarioM3_setConfigStubThenHass() {
  registry.define(GRAPH_CARD_TAG, GraphCard);
  const el = makeFreshCard();
  const createBefore = createCount;
  el.setConfig({ profile: STUB_PROFILE_VALUE });
  el.hass = fakeHass(STUB_PROFILE_VALUE);
  await settle();
  if (createCount !== createBefore || el.graphs.size !== 0) throw new Error("scenario M3: setConfig(stub) -> hass must build nothing");
}

async function scenarioM4_hassThenSetConfigStub() {
  registry.define(GRAPH_CARD_TAG, GraphCard);
  const el = makeFreshCard();
  const createBefore = createCount;
  el.hass = fakeHass(STUB_PROFILE_VALUE);
  el.setConfig({ profile: STUB_PROFILE_VALUE });
  await settle();
  if (createCount !== createBefore || el.graphs.size !== 0) throw new Error("scenario M4: hass -> setConfig(stub) must build nothing");
}

async function scenarioM5_multipleStubSetConfigCallsBuildNothing() {
  registry.define(GRAPH_CARD_TAG, GraphCard);
  const el = makeFreshCard();
  const createBefore = createCount;
  el.setConfig({ profile: STUB_PROFILE_VALUE });
  el.setConfig({ profile: STUB_PROFILE_VALUE, title: "Nog een keer" });
  el.setConfig({ profile: STUB_PROFILE_VALUE, text_size: "large" });
  el.hass = fakeHass(STUB_PROFILE_VALUE);
  await settle();
  if (createCount !== createBefore || el.graphs.size !== 0) throw new Error("scenario M5: repeated stub setConfig() calls must build nothing");
}

async function scenarioM6_stubWithDisplayGraphsBuildsNothingButKeepsDisplaySelection() {
  registry.define(GRAPH_CARD_TAG, GraphCard);
  const el = makeFreshCard();
  const createBefore = createCount;
  el.setConfig({ profile: STUB_PROFILE_VALUE, display: "graphs" });
  el.hass = fakeHass(STUB_PROFILE_VALUE);
  await settle();
  if (createCount !== createBefore || el.graphs.size !== 0) throw new Error("scenario M6: stub with display: graphs must still build nothing");
  if (el.config.display !== "graphs") throw new Error("scenario M6: the editor's display: graphs selection must not be changed to compact");
}

async function scenarioM7_validProfileSwitchedToStubMidPrefixResolutionBuildsNothing() {
  registry.define(GRAPH_CARD_TAG, GraphCard);
  const el = makeFreshCard();
  let releaseGate;
  const gate = new Promise((resolve) => { releaseGate = resolve; });
  el.setConfig({ profile: "order_test_profiel" });
  const createBefore = createCount;
  el.hass = fakeHassGated("order_test_profiel", gate); // initialize() now blocked inside listStatistics()
  await Promise.resolve();
  el.setConfig({ profile: STUB_PROFILE_VALUE }); // switched to the stub while the old resolution is still in flight
  releaseGate(); // let the *stale* initialize() run continue and see it has been superseded
  await settle();
  if (createCount !== createBefore) throw new Error("scenario M7: a switch to the stub profile during prefix resolution must still build nothing");
  if (el.graphs.size !== 0) throw new Error("scenario M7: no graph may end up attached after switching to the stub mid-resolution");
  if (el.hint !== "Kies een FITAGE-profiel in de kaarteditor.") throw new Error("scenario M7: the stub hint must win");
}

async function scenarioM8_stubLaterSwitchedToValidProfileBuildsOnlyAfterward() {
  registry.define(GRAPH_CARD_TAG, GraphCard);
  const el = makeFreshCard();
  el.setConfig({ profile: STUB_PROFILE_VALUE });
  el.hass = fakeHass("order_test_profiel");
  await settle();
  const createBeforeSwitch = createCount;
  if (el.graphs.size !== 0) throw new Error("scenario M8: still on the stub, nothing may be built yet");
  el.setConfig({ profile: "order_test_profiel" });
  el.hass = fakeHass("order_test_profiel");
  await settle();
  if (el.graphs.size !== 1) throw new Error("scenario M8: switching to a valid profile must build its graph");
  if (createCount === createBeforeSwitch) throw new Error("scenario M8: createCardElement() must actually have run after switching away from the stub");
}

async function scenarioM9_validProfileWithCurrentPrefixKeepsWorking() {
  registry.define(GRAPH_CARD_TAG, GraphCard);
  const el = makeFreshCard();
  el.setConfig({ profile: "order_test_profiel" });
  el.hass = fakeHass("order_test_profiel");
  await settle();
  if (el.graphs.size !== 1) throw new Error("scenario M9: a valid profile with a resolvable prefix must still build its graph normally");
  if (el.error) throw new Error("scenario M9: a valid profile must not show an error: " + el.error);
  if (!el.ready) throw new Error("scenario M9: a valid profile must reach the ready state");
}

async function scenarioK_theOldOrderReproducesTheSameCrash() {
  // Demonstrates the exact failure this fix closes: the *old* invariant
  // (graph.hass !== this._hass) does not reject two undefined values, so a
  // graph built while hass is genuinely missing slips through and a nested
  // element reading .hass.config crashes exactly like hui-graph-header-footer.
  const graph = {};
  const cardHass = undefined; // this._hass, as it would be if createGraphs() ran without the new guard
  graph.hass = cardHass;
  const oldInvariantWouldReject = graph.hass !== cardHass;
  if (oldInvariantWouldReject) {
    throw new Error("scenario K: the old equality-only invariant was expected to (wrongly) accept this");
  }
  let threw = null;
  try {
    void graph.hass.config;
  } catch (e) {
    threw = e;
  }
  if (!(threw instanceof TypeError)) {
    throw new Error("scenario K: reading .config off a graph with no real hass must throw the same TypeError Home Assistant does");
  }
}

(async () => {
  await scenarioA_setConfigBeforeAttach();
  await scenarioF_assigningHassBeforeUpgradeIsDemonstrablyLost();
  await scenarioB_rerenderDuringInFlightCreateGraphs();
  await scenarioC_compactSwitchIsSafe();
  await scenarioD_periodSwitchIsSafe();
  await scenarioE_editorPreviewReconfigureIsSafe();
  await scenarioG_setConfigWithoutHassBuildsNothing();
  await scenarioH_hassArrivesAfterSetConfigBuildsExactlyOnce();
  await scenarioI_multipleSetConfigBeforeHassOnlyBuildsTheLast();
  await scenarioJ_cardRemovedBeforeDeferredBuildIsNeverAttached();
  await scenarioL_createGraphsCalledDirectlyWithoutHassDefersAndLaterResumesOnce();
  await scenarioM1_singleStubPreviewCreatesNothing();
  await scenarioM2_twoSimultaneousStubPreviewsCreateNothing();
  await scenarioM3_setConfigStubThenHass();
  await scenarioM4_hassThenSetConfigStub();
  await scenarioM5_multipleStubSetConfigCallsBuildNothing();
  await scenarioM6_stubWithDisplayGraphsBuildsNothingButKeepsDisplaySelection();
  await scenarioM7_validProfileSwitchedToStubMidPrefixResolutionBuildsNothing();
  await scenarioM8_stubLaterSwitchedToValidProfileBuildsOnlyAfterward();
  await scenarioM9_validProfileWithCurrentPrefixKeepsWorking();
  await scenarioK_theOldOrderReproducesTheSameCrash();
  if (violations.length) {
    console.error(violations.join("\n"));
    process.exit(1);
  }
  console.log("ALL LIFECYCLE CHECKS PASSED");
})().catch((e) => { console.error(e.stack || e); process.exit(1); });
"""


def run_async(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))

    return wrapped


def fake_hass() -> SimpleNamespace:
    http = SimpleNamespace(async_register_static_paths=AsyncMock())
    config = SimpleNamespace(config_dir="/tmp")
    return SimpleNamespace(data={}, http=http, config=config)


def storage_lovelace_data(items: dict[str, dict] | None = None):
    """Build a real (non-mocked) storage-mode LovelaceData/ResourceStorageCollection
    pair, pre-loaded with `items` so tests exercise Home Assistant's own
    resource collection class instead of a hand-rolled stand-in.

    Store I/O is bypassed by setting `loaded = True` and seeding `.data`
    directly, matching how tests avoid real disk access elsewhere; callers
    still need to patch Store.async_delay_save since async_create_item/
    async_update_item schedule one.
    """
    from homeassistant.components.lovelace import LovelaceData
    from homeassistant.components.lovelace.const import LOVELACE_DATA, MODE_STORAGE
    from homeassistant.components.lovelace.resources import ResourceStorageCollection

    hass = fake_hass()
    resources = ResourceStorageCollection(hass, None)
    resources.loaded = True
    resources.data = dict(items or {})
    hass.data[LOVELACE_DATA] = LovelaceData(
        resource_mode=MODE_STORAGE,
        dashboards={},
        resources=resources,
        yaml_dashboards={},
    )
    return hass, resources


def test_bundled_card_ships_in_the_expected_distribution_location() -> None:
    assert CARD_PATH.is_file()


def test_bundled_card_is_version_0_6_4() -> None:
    assert CARD_PATH.read_text(encoding="utf-8").startswith('const VERSION = "0.6.4";')


def test_card_version_constant_matches_the_javascript_version() -> None:
    """custom_components/fitage/frontend.py hardcodes CARD_VERSION instead of
    reading it from the JS file at runtime (that would be a blocking file
    read during async_setup). This test is the only place allowed to read
    the file to keep the two in sync."""
    content = CARD_PATH.read_text(encoding="utf-8")
    match = _JS_VERSION_RE.search(content[:200])
    assert match is not None
    assert CARD_VERSION == match.group(1)


def test_bundled_card_registers_card_and_editor_elements() -> None:
    content = CARD_PATH.read_text(encoding="utf-8")
    assert 'customElements.define("fitage-card"' in content
    assert 'customElements.define("fitage-card-editor"' in content


def test_bundled_card_element_registration_is_idempotent() -> None:
    """Guards the frontend JS's own double-registration guards, which stay
    unchanged: the card must survive being imported more than once (e.g. a
    stale extra_js_url still importing it alongside the new Lovelace
    resource) without throwing on a duplicate customElements.define."""
    content = CARD_PATH.read_text(encoding="utf-8")
    assert 'if(!customElements.get("fitage-card"))customElements.define(' in content
    assert (
        'if(!customElements.get("fitage-card-editor"))customElements.define(' in content
    )
    assert 'window.customCards.some(c=>c.type==="fitage-card")' in content


def test_static_url_path_matches_the_bundled_card() -> None:
    assert STATIC_URL_PATH == "/fitage/fitage-card.js"


def test_module_url_is_exactly_the_expected_value() -> None:
    assert MODULE_URL == "/fitage/fitage-card.js?v=0.6.4"


def test_default_stub_profile_shows_a_neutral_instruction_in_source() -> None:
    """Static guard (always runs, no Node.js needed): the default stub
    preview (getStubConfig()'s profile: "jouw_profiel") must show a neutral
    instruction instead of the red "kon niet betrouwbaar worden gekoppeld"
    error, while a genuinely filled-in but invalid profile must still raise
    that error - see test_default_stub_profile_shows_hint_not_a_red_error
    for the real-Node.js behavioral proof of this distinction."""
    content = CARD_PATH.read_text(encoding="utf-8")
    assert 'const STUB_PROFILE = "jouw_profiel";' in content
    assert "getStubConfig() { return { profile: STUB_PROFILE }; }" in content
    assert "this.config.profile === STUB_PROFILE" in content
    assert 'this.hint = "Kies een FITAGE-profiel in de kaarteditor."' in content
    assert (
        'throw Error("Het juiste FITAGE-profiel kon niet betrouwbaar worden gekoppeld.")'
        in content
    )
    assert (
        'throw Error("Voor dit profiel zijn geen FITAGE-statistieken gevonden.")'
        in content
    )


@pytest.mark.skipif(NODE_BIN is None, reason="no local Node.js runtime available")
def test_default_stub_profile_shows_hint_not_a_red_error() -> None:
    """Real-Node.js behavioral proof: load the actual bundled card under a
    minimal customElements/HTMLElement stub and drive setConfig()/hass the
    same way Home Assistant's card picker preview does."""
    result = _run_node_js(_STUB_HINT_JS_HARNESS)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL JS BEHAVIOR CHECKS PASSED" in result.stdout


@pytest.mark.skipif(NODE_BIN is None, reason="no local Node.js runtime available")
def test_graph_element_is_never_connected_to_the_dom_before_it_is_configured() -> None:
    """Regression test for "TypeError: Cannot read properties of undefined
    (reading 'config')" at hui-graph-header-footer.ts:163, in
    _subscribeHistory(), called from connectedCallback(). Drives the real
    createGraphs()/render() through a faithful simulation of Home
    Assistant's own createCardElement() lazy-loading race (see the harness
    docstring above for the exact Core-adjacent source reference) and checks
    five scenarios: setConfig() before DOM attachment, a rerender while a
    new generation is still loading, switching between graphs and compact,
    rapid period switching, and an editor-preview reconfigure mid-flight."""
    result = _run_node_js(_GRAPH_LIFECYCLE_JS_HARNESS)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL LIFECYCLE CHECKS PASSED" in result.stdout


@pytest.mark.skipif(NODE_BIN is None, reason="no local Node.js runtime available")
def test_find_prefix_selects_the_real_weight_metric_deterministically() -> None:
    """findPrefix() must never mistake a statistic ID ending in
    "_fat_free_weight" for the "weight" metric just because it also ends in
    "_weight" as a substring, must prefer the display name FITAGE's own
    statistics.py writes into statistic metadata over any value comparison,
    and must refuse to guess - returning null - whenever two candidates are
    equally plausible, whether by colliding display name or by value."""
    result = _run_node_js(_FIND_PREFIX_JS_HARNESS)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL FIND-PREFIX CHECKS PASSED" in result.stdout


@pytest.mark.skipif(NODE_BIN is None, reason="no local Node.js runtime available")
def test_assessment_color_and_label_mapping_matches_the_official_research() -> None:
    """metricHtml() must color "Actueel" and show its category label using the
    official FITAGE per-category colors and text reverse-engineered from the
    real app (never a zone index, a gradient, or normal_min/normal_max), fall
    back to today's exact orange with no label when the assessment is missing
    or unknown, and still let an explicit, valid manual current_color win."""
    result = _run_node_js(_ASSESSMENT_JS_HARNESS)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL ASSESSMENT CHECKS PASSED" in result.stdout


@pytest.mark.skipif(NODE_BIN is None, reason="no local Node.js runtime available")
def test_assessment_label_language_follows_home_assistant_language() -> None:
    """Drives the real, bundled normalizeLanguage()/cardLanguage()/
    levelLabelText() through metricHtml() for every case the FITAGE language
    normalization proposal specifies: direct base languages, regional
    variants, the fr/ja/ru/cs aliases (plain and with a region suffix), the
    French fa file (never Persian - HA's "fa" itself must be blocked to
    English), simplified/traditional Chinese (including the extended
    zh-Hans-CN/zh-Hant-TW forms), pt-BR falling back to the (Portugal) pt
    file, a wholly unknown language, and a known key ("hight") with no
    translation in an otherwise fully supported language falling back to
    English - never staying untranslated, fabricated or raising."""
    harness = (
        _LOAD_CARD_JS_PRELUDE
        + r"""
const WEIGHT_METRIC = { key: "weight", title: "Gewicht", entity: "weight", unit: "kg" };
function stateWithAssessment(assessment) {
  return { state: "80", attributes: { normal_min: 60, normal_max: 90, unit_of_measurement: "kg", assessment } };
}
function renderFor(language, assessment) {
  const el = Object.create(Card.prototype);
  el.config = { title: "FITAGE", display: "graphs" };
  el.slug = "test_profiel";
  el._hass = { states: { "sensor.test_profiel_weight": stateWithAssessment(assessment) }, language };
  return el.metricHtml(WEIGHT_METRIC);
}
const cases = [
  // Dutch and English, unchanged from before this card supported more.
  ["nl", "normal", "Normaal"],
  ["nl-NL", "normal", "Normaal"],
  ["en", "normal", "Normal"],
  // Direct base languages - "essential_fat" is used for the five (de, es,
  // pt, ro, tr) whose own "normal" text happens to equal the English word,
  // so a real per-language lookup is distinguishable from an accidental
  // English fallback; the rest use "normal" directly.
  ["de", "essential_fat", "Essentielles Fett"],
  ["es", "essential_fat", "Grass esencial"],
  ["pt", "essential_fat", "Gordura essencial"],
  ["ro", "essential_fat", "Grăsime esențială"],
  ["tr", "essential_fat", "Temel Yağ"],
  ["it", "normal", "Normale"],
  ["ar", "normal", "عادي"],
  ["hu", "normal", "Normál"],
  ["pl", "normal", "Prawidłowa waga"],
  ["sk", "normal", "Štandardné"],
  ["th", "normal", "มาตรฐาน"],
  ["vi", "normal", " Bình thường"],
  ["ko", "normal", "정상체중"],
  // Regional variant of a direct base language.
  ["de-AT", "essential_fat", "Essentielles Fett"],
  // FITAGE aliases (fr->fa is covered separately below), plain and with a
  // region suffix stripped first.
  ["ja", "normal", "正常"],
  ["ja-JP", "normal", "正常"],
  ["ru", "normal", "Нормальный вес"],
  ["ru-RU", "normal", "Нормальный вес"],
  ["cs", "normal", "Normální"],
  ["cs-CZ", "normal", "Normální"],
  // fr/fr-FR/fr-CA must select the French FITAGE file (code "fa"), proven
  // by "Ordinaire" - "normal" translated into French, not English/Dutch.
  ["fr", "normal", "Ordinaire"],
  ["fr-FR", "normal", "Ordinaire"],
  ["fr-CA", "normal", "Ordinaire"],
  // HA's "fa" (Persian) and its regional forms must never select the
  // French "fa" file - they must fall back to English.
  ["fa", "normal", "Normal"],
  ["fa-IR", "normal", "Normal"],
  // Simplified/traditional Chinese, including the extended script+region
  // forms, distinguished via "athletes" (zh_CN/zh_TW differ there).
  ["zh", "athletes", "健壮"],
  ["zh-CN", "athletes", "健壮"],
  ["zh-Hans", "athletes", "健壮"],
  ["zh-Hans-CN", "athletes", "健壮"],
  ["zh-TW", "athletes", "健壯"],
  ["zh-Hant", "athletes", "健壯"],
  ["zh-Hant-TW", "athletes", "健壯"],
  // pt-BR has no FITAGE file of its own and must fall back to the
  // (Portugal) "pt" file, not to English.
  ["pt-BR", "essential_fat", "Gordura essencial"],
  // A wholly unknown/unsupported language falls back to English.
  ["sw", "normal", "Normal"],
  ["da", "normal", "Normal"], // deliberately not yet implemented (§6)
  // A known key with no researched translation in an otherwise fully
  // supported language ("hight" only has nl/en) falls back to English,
  // never staying blank or showing a fabricated non-English guess.
  ["fr", "hight", "High"],
];
const failures = [];
for (const [language, assessment, expected] of cases) {
  const html = renderFor(language, assessment);
  if (!html.includes(`>${expected}<`)) {
    failures.push(`language "${language}", key "${assessment}": expected label "${expected}", got: ${html}`);
  }
}
if (failures.length) { console.error(failures.join("\n")); process.exit(1); }
console.log("ALL LANGUAGE CHECKS PASSED");
"""
    )
    result = _run_node_js(harness)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL LANGUAGE CHECKS PASSED" in result.stdout


_DERIVED_MASS_ASSESSMENT_JS_HARNESS = (
    _LOAD_CARD_JS_PRELUDE
    + r"""
// METRICS itself is a top-level `const` inside the eval()'d card source, so
// (like every other harness in this file) it stays confined to that eval
// call and is not reachable from here - these mirror its real entries for
// the keys under test, including entity: null and the "water" metric's own
// live entity suffix being "hydration" (not "water"), instead of guessing
// "sensor.<slug>_water", which would silently no-op the lookup.
const BODY_FAT_MASS_METRIC = { key: "body_fat_mass", title: "Vetmassa", entity: null, unit: "kg" };
const BODY_WATER_MASS_METRIC = { key: "body_water_mass", title: "Watermassa", entity: null, unit: "kg" };
const PROTEIN_MASS_METRIC = { key: "protein_mass", title: "Eiwitmassa", entity: null, unit: "kg" };
const FAT_FREE_WEIGHT_METRIC = { key: "fat_free_weight", title: "Vetvrij gewicht", entity: null, unit: "kg" };
const SCORE_METRIC = { key: "score", title: "Gezondheidsscore", entity: null, unit: "" };
const MASS_METRICS_BY_KEY = {
  body_fat_mass: BODY_FAT_MASS_METRIC,
  body_water_mass: BODY_WATER_MASS_METRIC,
  protein_mass: PROTEIN_MASS_METRIC,
};

function makeMassCard(states) {
  const el = Object.create(Card.prototype);
  el.config = { title: "FITAGE", display: "graphs" };
  el.slug = "test_profiel";
  el._hass = { states, language: "nl" };
  el.latest = new Map([
    ["body_fat_mass", 27.21],
    ["body_water_mass", 48.3],
    ["protein_mass", 15.25],
  ]);
  return el;
}

const FULL_STATES = {
  "sensor.test_profiel_weight": { state: "94.15", attributes: {} },
  "sensor.test_profiel_bodyfat": {
    state: "28.9",
    attributes: { assessment: "overweight", normal_min: 17, normal_max: 25 },
  },
  "sensor.test_profiel_hydration": {
    state: "51.3",
    attributes: { assessment: "normal", normal_min: 50, normal_max: 65 },
  },
  "sensor.test_profiel_protein": {
    state: "16.2",
    attributes: { assessment: "normal", normal_min: 16, normal_max: 18 },
  },
};

const failures = [];
function check(label, condition) { if (!condition) failures.push(label); }

// 1) body_fat_mass must inherit "overweight" (and its official color/label)
// from the "bodyfat" percentage sensor - never recomputed from the kg bounds.
{
  const el = makeMassCard(FULL_STATES);
  const metric = BODY_FAT_MASS_METRIC;
  const v = el.values(metric);
  check("body_fat_mass assessment must equal bodyfat's ('overweight')", v.assessment === "overweight");
  check("body_fat_mass normal_min/max stay derived from bodyfat's own range", v.min === 94.15 * 17 / 100 && v.max === 94.15 * 25 / 100);
  const html = el.metricHtml(metric);
  check("body_fat_mass current cell must use overweight's official color #E3B026", html.includes('id="current-body_fat_mass" class="current" style="color:#E3B026"'));
  check("body_fat_mass must show the Dutch 'Overgewicht' label", html.includes(">Overgewicht<"));
}

// 2) body_water_mass must inherit "normal" from "water" (entity id "hydration").
{
  const el = makeMassCard(FULL_STATES);
  const metric = BODY_WATER_MASS_METRIC;
  const v = el.values(metric);
  check("body_water_mass assessment must equal water's ('normal')", v.assessment === "normal");
  const html = el.metricHtml(metric);
  check("body_water_mass current cell must use normal's official color #46C083", html.includes('id="current-body_water_mass" class="current" style="color:#46C083"'));
  check("body_water_mass must show the Dutch 'Normaal' label", html.includes(">Normaal<"));
}

// 3) protein_mass must inherit "normal" from "protein".
{
  const el = makeMassCard(FULL_STATES);
  const metric = PROTEIN_MASS_METRIC;
  const v = el.values(metric);
  check("protein_mass assessment must equal protein's ('normal')", v.assessment === "normal");
  const html = el.metricHtml(metric);
  check("protein_mass current cell must use normal's official color #46C083", html.includes('id="current-protein_mass" class="current" style="color:#46C083"'));
  check("protein_mass must show the Dutch 'Normaal' label", html.includes(">Normaal<"));
}

// 4) A missing percentage source (e.g. not yet loaded, or gender unknown so
// assessment.py omitted it) must not error and must keep today's exact
// fallback: no inline color, no label - never a fabricated assessment.
{
  const statesWithoutSources = { "sensor.test_profiel_weight": FULL_STATES["sensor.test_profiel_weight"] };
  const el = makeMassCard(statesWithoutSources);
  for (const key of ["body_fat_mass", "body_water_mass", "protein_mass"]) {
    const metric = MASS_METRICS_BY_KEY[key];
    const v = el.values(metric);
    check(`${key} assessment must be undefined when its percentage source is missing`, v.assessment === undefined);
    const html = el.metricHtml(metric);
    check(`${key} must not set an inline current color when its source is missing`, !new RegExp(`id="current-${key}" class="current" style=`).test(html));
    check(`${key} must render its assessment element hidden and empty when its source is missing`, html.includes(`id="assessment-${key}" class="assessment" hidden></small>`));
  }
}

// 5) Fat-free weight and the health score have no percentage source mapping
// and must never pick up an assessment, even with a fully populated hass.
{
  const el = makeMassCard(FULL_STATES);
  for (const metric of [FAT_FREE_WEIGHT_METRIC, SCORE_METRIC]) {
    const v = el.values(metric);
    check(`${metric.key} must keep no assessment (untouched fallback behavior)`, v.assessment === undefined);
  }
}

if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}
console.log("ALL DERIVED MASS ASSESSMENT CHECKS PASSED");
"""
)


@pytest.mark.skipif(NODE_BIN is None, reason="no local Node.js runtime available")
def test_derived_mass_metrics_inherit_assessment_from_percentage_sensor() -> None:
    """body_fat_mass, body_water_mass and protein_mass have no live HA entity
    of their own in METRICS (entity: null), so values() must copy `assessment`
    from the corresponding percentage sensor (bodyfat/water/protein) - the
    reliable official category source - exactly like it already does for
    normal_min/normal_max, instead of leaving it undefined or recomputing a
    category from the kg bounds. A missing source must keep the existing
    orange/no-label fallback, and fat_free_weight/score must stay untouched."""
    result = _run_node_js(_DERIVED_MASS_ASSESSMENT_JS_HARNESS)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL DERIVED MASS ASSESSMENT CHECKS PASSED" in result.stdout


def test_level_colors_and_labels_cover_every_current_assessment_key() -> None:
    """Every assessment key custom_components/fitage/assessment.py can
    actually produce today (ASSESSMENT_LABELS) must have both an official
    color and an official label in the bundled card, so nothing the backend
    can send is ever silently left with no color or no text. Runs without
    Node.js - a plain, static cross-check of the two source files."""
    content = CARD_PATH.read_text(encoding="utf-8")
    colors_block = re.search(r"const LEVEL_COLORS = \{(.*?)\n\};", content, re.DOTALL)
    labels_block = re.search(r"const LEVEL_LABELS = \{(.*?)\n\};", content, re.DOTALL)
    assert colors_block is not None
    assert labels_block is not None
    for key in ASSESSMENT_LABELS:
        assert re.search(rf"(?<!\w){re.escape(key)}:", colors_block.group(1)), (
            f"assessment key {key!r} (used by assessment.py) has no color in "
            "fitage-card.js's LEVEL_COLORS"
        )
        assert re.search(rf"(?<!\w){re.escape(key)}:", labels_block.group(1)), (
            f"assessment key {key!r} (used by assessment.py) has no label in "
            "fitage-card.js's LEVEL_LABELS"
        )
    # "hight" is a typo that exists in the official FITAGE app itself, not
    # producible by assessment.py today; it must still be preserved verbatim
    # for whenever assessment.py starts using it, per the color research.
    assert re.search(r"(?<!\w)hight:", colors_block.group(1))
    assert re.search(r"(?<!\w)hight:", labels_block.group(1))


def test_expected_level_labels_cover_exactly_every_current_assessment_key() -> None:
    """EXPECTED_LEVEL_LABELS (this test file's own record of the officially
    researched text) must claim exactly the assessment keys assessment.py can
    actually produce today - no more, no less - so a future change to either
    side is caught here rather than silently drifting apart. "hight" is
    deliberately excluded: it is not part of ASSESSMENT_LABELS."""
    assert set(EXPECTED_LEVEL_LABELS) == set(ASSESSMENT_LABELS)


@pytest.mark.skipif(NODE_BIN is None, reason="no local Node.js runtime available")
def test_all_supported_languages_have_the_exact_official_label_text() -> None:
    """Every one of FITAGE_SUPPORTED_LANGUAGES must have the exact, official
    text (EXPECTED_LEVEL_LABELS) for every assessment key assessment.py can
    produce, read back from the real, bundled LEVEL_LABELS object (not by
    re-typing it a second time) - and none of the deliberately not-yet-
    implemented FITAGE codes (da, sv, fi, no, el, is) may appear anywhere in
    it, guarding against implementing them ahead of the approved research."""
    # LEVEL_LABELS is a top-level `const` inside the card source: a direct
    # eval() of `src` alone (as _LOAD_CARD_JS_PRELUDE does) confines it to
    # that eval call, unreachable afterward - only `function` declarations
    # leak into the surrounding scope that way (see METRICS's comment
    # elsewhere in this file for the same constraint). The dump statement is
    # therefore appended to `src` itself and evaluated together in one call,
    # sharing its lexical scope, instead of reusing _LOAD_CARD_JS_PRELUDE.
    harness = r"""
class FakeElement {
  attachShadow() { this.shadowRoot = { innerHTML: "", querySelector: () => null, querySelectorAll: () => [] }; return this.shadowRoot; }
}
global.HTMLElement = FakeElement;
global.customElements = { registry: new Map(), get(n){return this.registry.get(n)}, define(n,c){this.registry.set(n,c)} };
global.window = { customCards: undefined, loadCardHelpers: async () => ({ createCardElement: () => ({}) }) };
global.document = { createElement: () => ({}) };

const fs = require("fs");
const src = fs.readFileSync(CARD_PATH, "utf8");
eval(src + `
console.log("===LEVEL_LABELS_JSON_START===");
console.log(JSON.stringify(LEVEL_LABELS));
console.log("===LEVEL_LABELS_JSON_END===");
`);
"""
    result = _run_node_js(harness)
    assert result.returncode == 0, result.stdout + result.stderr
    match = re.search(
        r"===LEVEL_LABELS_JSON_START===\n(.*)\n===LEVEL_LABELS_JSON_END===",
        result.stdout,
        re.DOTALL,
    )
    assert match is not None, result.stdout + result.stderr
    actual = json.loads(match.group(1))

    not_yet_implemented = {"da", "sv", "fi", "no", "el", "is"}
    failures: list[str] = []
    for key, expected_by_lang in EXPECTED_LEVEL_LABELS.items():
        actual_by_lang = actual.get(key, {})
        for lang in not_yet_implemented:
            if lang in actual_by_lang:
                failures.append(
                    f"{key!r} must not yet have a {lang!r} entry (not "
                    "implemented per the approved research)"
                )
        for lang in FITAGE_SUPPORTED_LANGUAGES:
            actual_text = actual_by_lang.get(lang)
            expected_text = expected_by_lang[lang]
            if actual_text != expected_text:
                failures.append(
                    f"{key!r}[{lang!r}]: expected {expected_text!r}, got {actual_text!r}"
                )
    assert not failures, "\n".join(failures)


@pytest.mark.skipif(NODE_BIN is None, reason="no local Node.js runtime available")
def test_all_metric_titles_and_current_label_match_the_official_text() -> None:
    """METRIC_LABELS (all 14 metrics) and CURRENT_LABELS must match
    EXPECTED_METRIC_LABELS/EXPECTED_CURRENT_LABELS exactly, read back from
    the real, bundled objects - including the six deliberate Dutch
    exceptions - and must never claim any of the not-yet-implemented FITAGE
    codes. Same dump-and-compare technique as LEVEL_LABELS, for the same
    `const`-scoping reason documented on that test."""
    harness = r"""
class FakeElement {
  attachShadow() { this.shadowRoot = { innerHTML: "", querySelector: () => null, querySelectorAll: () => [] }; return this.shadowRoot; }
}
global.HTMLElement = FakeElement;
global.customElements = { registry: new Map(), get(n){return this.registry.get(n)}, define(n,c){this.registry.set(n,c)} };
global.window = { customCards: undefined, loadCardHelpers: async () => ({ createCardElement: () => ({}) }) };
global.document = { createElement: () => ({}) };

const fs = require("fs");
const src = fs.readFileSync(CARD_PATH, "utf8");
eval(src + `
console.log("===METRIC_LABELS_JSON_START===");
console.log(JSON.stringify({metrics: METRIC_LABELS, current: CURRENT_LABELS}));
console.log("===METRIC_LABELS_JSON_END===");
`);
"""
    result = _run_node_js(harness)
    assert result.returncode == 0, result.stdout + result.stderr
    match = re.search(
        r"===METRIC_LABELS_JSON_START===\n(.*)\n===METRIC_LABELS_JSON_END===",
        result.stdout,
        re.DOTALL,
    )
    assert match is not None, result.stdout + result.stderr
    dumped = json.loads(match.group(1))
    actual_metrics = dumped["metrics"]
    actual_current = dumped["current"]

    not_yet_implemented = {"da", "sv", "fi", "no", "el", "is"}
    failures: list[str] = []
    for key, expected_by_lang in EXPECTED_METRIC_LABELS.items():
        actual_by_lang = actual_metrics.get(key, {})
        for lang in not_yet_implemented:
            if lang in actual_by_lang:
                failures.append(f"metric {key!r} must not yet have a {lang!r} entry")
        for lang in FITAGE_SUPPORTED_LANGUAGES:
            actual_text = actual_by_lang.get(lang)
            expected_text = expected_by_lang[lang]
            if actual_text != expected_text:
                failures.append(
                    f"metric {key!r}[{lang!r}]: expected {expected_text!r}, got {actual_text!r}"
                )
    for lang in not_yet_implemented:
        if lang in actual_current:
            failures.append(f"current label must not yet have a {lang!r} entry")
    for lang in EXPECTED_CURRENT_LABEL_FALLBACK_LANGUAGES:
        if lang in actual_current:
            failures.append(
                f"current label must not have its own {lang!r} entry - it is a "
                "deliberate English fallback (misleading official app text)"
            )
    for lang in FITAGE_SUPPORTED_LANGUAGES:
        if lang in EXPECTED_CURRENT_LABEL_FALLBACK_LANGUAGES:
            continue
        actual_text = actual_current.get(lang)
        expected_text = EXPECTED_CURRENT_LABELS[lang]
        if actual_text != expected_text:
            failures.append(
                f"current[{lang!r}]: expected {expected_text!r}, got {actual_text!r}"
            )
    assert not failures, "\n".join(failures)


def test_expected_metric_labels_cover_exactly_the_fourteen_card_metrics() -> None:
    """EXPECTED_METRIC_LABELS (this test file's own record) must claim
    exactly the 14 metric keys the card's own METRICS array defines - no
    more, no less - read directly from fitage-card.js, not re-typed."""
    content = CARD_PATH.read_text(encoding="utf-8")
    metrics_block = re.search(r"const METRICS = \[(.*?)\]\.map", content, re.DOTALL)
    assert metrics_block is not None
    metric_keys = set(re.findall(r'\["(\w+)",', metrics_block.group(1)))
    assert metric_keys == set(EXPECTED_METRIC_LABELS)


@pytest.mark.skipif(NODE_BIN is None, reason="no local Node.js runtime available")
def test_metric_titles_and_current_label_render_through_the_real_card() -> None:
    """metricTitle()/currentLabel() must actually be wired into the
    rendered <h2> and "current" label - verified through the real bundled
    metricHtml(), not by re-reading METRIC_LABELS/CURRENT_LABELS directly -
    for a supported language, an unknown language (English fallback), and
    the editor's metric checkbox list. Never a literal "undefined", "null",
    or the raw METRICS Dutch fallback text for a supported language."""
    harness = (
        _LOAD_CARD_JS_PRELUDE
        + r"""
const WEIGHT_METRIC = { key: "weight", title: "Gewicht", entity: "weight", unit: "kg" };
function stateFor(assessment) {
  return { state: "80", attributes: { normal_min: 60, normal_max: 90, unit_of_measurement: "kg", assessment } };
}
function renderFor(language) {
  const el = Object.create(Card.prototype);
  el.config = { title: "FITAGE", display: "graphs" };
  el.slug = "test_profiel";
  el._hass = { states: { "sensor.test_profiel_weight": stateFor("normal") }, language };
  return el.metricHtml(WEIGHT_METRIC);
}
const failures = [];
function check(label, condition) { if (!condition) failures.push(label); }

check("Dutch title", renderFor("nl").includes(">Gewicht<"));
check("Dutch current label (official 'Huidig', not 'Actueel')", renderFor("nl").includes(">Huidig<"));
check("Japanese title", renderFor("ja").includes(">体重<"));
check("Japanese current label", renderFor("ja").includes(">現在<"));
const unknown = renderFor("sw");
check("unknown language falls back to English title", unknown.includes(">Weight<"));
check("unknown language falls back to English current label", unknown.includes(">Current<"));
check("never a literal undefined", !unknown.includes("undefined"));
check("never a literal null", !unknown.includes(">null<"));

// Thai keeps its own (correct) official metric title, but must fall back
// to the English "Current" label - the official Thai "current" string
// ("กระแสน้ำ" = "water current"/"tide") is a false friend and must never
// appear here.
const thai = renderFor("th");
check("Thai still uses its own official metric title", thai.includes(">น้ำหนัก<"));
check("Thai current label falls back to English 'Current'", thai.includes(">Current<"));
check("Thai current label never shows the misleading official app text", !thai.includes("กระแสน้ำ"));

// Editor: metric checkbox labels and the "None" button both localized.
const Editor = customElements.get("fitage-card-editor");
const editorEl = Object.create(Editor.prototype);
editorEl.querySelector = () => ({ addEventListener(){} });
editorEl.querySelectorAll = () => [];
let editorHTML = "";
Object.defineProperty(editorEl, "innerHTML", { set(v){ editorHTML = v; }, get(){ return editorHTML; } });
editorEl._hass = { language: "de" };
editorEl.config = { profile: "test" };
editorEl.render();
check("editor metric checkbox uses the German title", editorHTML.includes(">Grundumsatz<"));

if (failures.length) { console.error(failures.join("\n")); process.exit(1); }
console.log("ALL METRIC RENDER CHECKS PASSED");
"""
    )
    result = _run_node_js(harness)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL METRIC RENDER CHECKS PASSED" in result.stdout


_HA_LOCALIZE_JS_HARNESS = (
    _LOAD_CARD_JS_PRELUDE
    + r"""
const WEIGHT_METRIC = { key: "weight", title: "Gewicht", entity: "weight", unit: "kg" };
function stateFor(assessment) {
  return { state: "80", attributes: { normal_min: 60, normal_max: 90, unit_of_measurement: "kg", assessment } };
}
function renderFor(hassExtra) {
  const el = Object.create(Card.prototype);
  el.config = { title: "FITAGE", display: "graphs" };
  el.slug = "test_profiel";
  el._hass = { states: { "sensor.test_profiel_weight": stateFor("normal") }, language: "de", ...hassExtra };
  return el.metricHtml(WEIGHT_METRIC);
}
const failures = [];
function check(label, condition) { if (!condition) failures.push(label); }

// 1) A real hass.localize() with official German text is used verbatim.
const withLocalize = renderFor({
  localize: (key) => ({
    "ui.panel.lovelace.editor.card.generic.minimum": "Minimum",
    "ui.panel.lovelace.editor.card.generic.maximum": "Maximum",
    "ui.common.loading": "Wird geladen",
  }[key] || ""),
});
check("official Minimum shown", withLocalize.includes(">Minimum<"));
check("official Maximum shown", withLocalize.includes(">Maximum<"));
check("official German Loading shown in the graph placeholder", withLocalize.includes('id="graph-weight">Wird geladen<'));

// 2) hass.localize missing entirely -> English fallback, never blank/undefined.
const withoutLocalize = renderFor({});
check("Minimum fallback", withoutLocalize.includes(">Minimum<"));
check("Maximum fallback", withoutLocalize.includes(">Maximum<"));
check("Loading fallback in the graph placeholder", withoutLocalize.includes('id="graph-weight">Loading<'));
check("never a literal undefined", !withoutLocalize.includes("undefined"));

// 3) hass.localize present but returns "" for this key (a real,
// undocumented HA translation gap, proven for some languages) -> the same
// English fallback, never an empty label.
const emptyLocalize = renderFor({ localize: () => "" });
check("empty hass.localize result still falls back to Minimum", emptyLocalize.includes(">Minimum<"));
check("empty hass.localize result still falls back to Maximum", emptyLocalize.includes(">Maximum<"));
check("empty hass.localize result still falls back to Loading", emptyLocalize.includes('id="graph-weight">Loading<'));

// 4) The editor's "None" button uses the official ui.common.none text,
// with the same English fallback when hass.localize is unavailable.
const Editor = customElements.get("fitage-card-editor");
function renderEditor(hassExtra) {
  const el = Object.create(Editor.prototype);
  el.querySelector = () => ({ addEventListener(){} });
  el.querySelectorAll = () => [];
  let html = "";
  Object.defineProperty(el, "innerHTML", { set(v){ html = v; }, get(){ return html; } });
  el._hass = { language: "de", ...hassExtra };
  el.config = { profile: "test" };
  el.render();
  return html;
}
check("official 'Kein' shown for the None button", renderEditor({ localize: (k) => (k === "ui.common.none" ? "Kein" : "") }).includes('id="none">Kein<'));
check("English 'None' fallback for the None button", renderEditor({}).includes('id="none">None<'));

if (failures.length) { console.error(failures.join("\n")); process.exit(1); }
console.log("ALL HA LOCALIZE CHECKS PASSED");
"""
)


@pytest.mark.skipif(NODE_BIN is None, reason="no local Node.js runtime available")
def test_ha_localize_used_for_minimum_maximum_loading_and_none_with_english_fallback() -> (
    None
):
    """Minimum/Maximum/Loading/None must come from the real, official
    hass.localize() when it provides them, and fall back to the exact
    English literal - never a blank string, "undefined", or the raw
    localization key - when hass.localize is unavailable or itself returns
    an empty string (a real, observed gap in some of HA's own official
    translations, e.g. Thai/Polish/Romanian for ui.common.none)."""
    result = _run_node_js(_HA_LOCALIZE_JS_HARNESS)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL HA LOCALIZE CHECKS PASSED" in result.stdout


_NUMBER_FORMAT_JS_HARNESS = (
    _LOAD_CARD_JS_PRELUDE
    + r"""
const failures = [];
function check(label, condition) { if (!condition) failures.push(label); }
function fmt(locale, value) {
  return Card.prototype.format.call({ _hass: { locale } }, value, "kg", "weight");
}

// hass.locale.number_format, all documented values (proven from the
// installed home-assistant-frontend bundle's own numberFormatToLocale()).
check("nl (language default) uses a decimal comma", fmt({ language: "nl", number_format: "language" }, 1234.5) === "1.234,5 kg");
check("en (language default) uses a decimal point", fmt({ language: "en", number_format: "language" }, 1234.5) === "1,234.5 kg");
check("comma_decimal forces en-US style regardless of language", fmt({ language: "de", number_format: "comma_decimal" }, 1234.5) === "1,234.5 kg");
check("decimal_comma forces de/es/it style", fmt({ language: "en", number_format: "decimal_comma" }, 1234.5) === "1.234,5 kg");
check("space_comma uses a space thousands separator and a decimal comma", fmt({ language: "en", number_format: "space_comma" }, 1234.5) === "1 234,5 kg" || fmt({ language: "en", number_format: "space_comma" }, 1234.5) === "1 234,5 kg");
check("quote_decimal (Swiss) uses an apostrophe thousands separator", fmt({ language: "en", number_format: "quote_decimal" }, 1234.5).includes("’") || fmt({ language: "en", number_format: "quote_decimal" }, 1234.5).includes("'"));
check("system falls back to the runtime default locale without crashing", typeof fmt({ language: "de", number_format: "system" }, 1234.5) === "string");

// German, French and Arabic follow their own language when number_format
// simply follows the language (HA's own default for a fresh profile).
check("de", fmt({ language: "de", number_format: "language" }, 1234.5) === "1.234,5 kg");
check("fr", fmt({ language: "fr", number_format: "language" }, 1234.5) === "1 234,5 kg" || fmt({ language: "fr", number_format: "language" }, 1234.5) === "1 234,5 kg");
check("ar does not crash and returns a string", typeof fmt({ language: "ar", number_format: "language" }, 1234.5) === "string");

// A syntactically invalid locale must never crash - falls back to English.
check("invalid locale never throws", (() => { try { fmt({ language: "not a locale!!" }, 1234.5); return true; } catch (e) { return false; } })());
check("invalid locale falls back to English-style formatting", fmt({ language: "not a locale!!" }, 1234.5) === "1,234.5 kg");

// A syntactically valid but unrecognized locale must not crash either.
check("unknown-but-valid locale never throws", (() => { try { fmt({ language: "xx-XX" }, 1234.5); return true; } catch (e) { return false; } })());

// Units always stay a separate, appended literal - never touched by the formatter.
check("unit stays untranslated and separate", fmt({ language: "de", number_format: "language" }, 5, "kg") !== undefined && Card.prototype.format.call({ _hass: { locale: { language: "de", number_format: "language" } } }, 5, "kg", "weight").endsWith(" kg"));

if (failures.length) { console.error(failures.join("\n")); process.exit(1); }
console.log("ALL NUMBER FORMAT CHECKS PASSED");
"""
)


@pytest.mark.skipif(NODE_BIN is None, reason="no local Node.js runtime available")
def test_number_formatting_follows_hass_locale_number_format() -> None:
    """format() must reproduce Home Assistant's own official
    hass.locale.number_format resolution (nl/en/de/fr/ar plus every
    documented number_format value), never crash on an invalid or merely
    unrecognized locale, and always keep the unit as a separate, untouched
    literal appended after the formatted number."""
    result = _run_node_js(_NUMBER_FORMAT_JS_HARNESS)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL NUMBER FORMAT CHECKS PASSED" in result.stdout


_PERIOD_LABEL_JS_HARNESS = (
    _LOAD_CARD_JS_PRELUDE
    + r"""
const failures = [];
function check(label, condition) { if (!condition) failures.push(label); }

function renderPeriods(hass) {
  const el = Object.create(Card.prototype);
  el.config = { title: "FITAGE", display: "graphs" };
  el._hass = hass;
  el.range = "1m";
  el.ready = false;
  el.available = [];
  el.graphs = new Map();
  el.shadowRoot = { querySelectorAll: () => [], querySelector: () => null };
  el.render();
  return el.shadowRoot.innerHTML;
}

// Representative languages, including the one proven Japanese exception.
check("Dutch 1j label", renderPeriods({ language: "nl" }).includes('data-range="1j"')
  && renderPeriods({ language: "nl" }).match(/data-range="1j"[^>]*>([^<]*)</)[1] === "1 jr");
check("English 1j label uses the narrow 'y' form", renderPeriods({ language: "en" }).match(/data-range="1j"[^>]*>([^<]*)</)[1] === "1y");
check("Japanese 1j label uses real Japanese text (short), not Latin 'jp'/'y'", renderPeriods({ language: "ja" }).match(/data-range="1j"[^>]*>([^<]*)</)[1] === "1 年");
check("Japanese 7d label uses real Japanese text", renderPeriods({ language: "ja" }).match(/data-range="7d"[^>]*>([^<]*)</)[1] === "7 日");
check("Arabic 1m label does not crash and is non-empty", renderPeriods({ language: "ar" }).match(/data-range="1m"[^>]*>([^<]*)</)[1].length > 0);
check("Traditional Chinese 3m label is non-empty", renderPeriods({ language: "zh-Hant" }).match(/data-range="3m"[^>]*>([^<]*)</)[1].length > 0);

// Internal range/days are never affected by language.
const el = Object.create(Card.prototype);
el.range = "1j";
check("the 'days' getter for 1j stays 365 regardless of language", el.days === 365);

if (failures.length) { console.error(failures.join("\n")); process.exit(1); }
console.log("ALL PERIOD LABEL CHECKS PASSED");
"""
)


@pytest.mark.skipif(NODE_BIN is None, reason="no local Node.js runtime available")
def test_period_button_labels_are_localized_while_internal_ranges_stay_fixed() -> None:
    """The visible period button label must be generated per the real HA
    language via Intl.NumberFormat's unit narrow/short form, while the
    internal range key ("7d","14d","1m","3m","1j") and the derived `days`
    lookup must never change with the language - proven for Dutch, English,
    Japanese (the one confirmed narrow-is-not-localized exception, verified
    across all 21 supported languages before choosing it), Arabic, and
    Traditional Chinese."""
    result = _run_node_js(_PERIOD_LABEL_JS_HARNESS)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL PERIOD LABEL CHECKS PASSED" in result.stdout


@pytest.mark.skipif(NODE_BIN is None, reason="no local Node.js runtime available")
def test_card_adopts_document_direction_for_rtl_on_connect() -> None:
    """FitageCard must copy document.dir onto itself when connected, the
    same pattern Home Assistant's own frontend components use (verified in
    the installed home-assistant-frontend bundle) - no hardcoded RTL
    language list."""
    harness = r"""
class FakeElement {
  attachShadow() { this.shadowRoot = { innerHTML: "", querySelector: () => null, querySelectorAll: () => [] }; return this.shadowRoot; }
}
global.HTMLElement = FakeElement;
global.customElements = { registry: new Map(), get(n){return this.registry.get(n)}, define(n,c){this.registry.set(n,c)} };
global.window = { customCards: undefined, loadCardHelpers: async () => ({ createCardElement: () => ({}) }) };
global.document = { createElement: () => ({}), dir: "rtl" };
const fs = require("fs");
eval(fs.readFileSync(CARD_PATH, "utf8"));
const Card = customElements.get("fitage-card");
const el = new Card();
el.connectedCallback();
if (el.dir !== "rtl") { console.error("expected dir 'rtl', got " + JSON.stringify(el.dir)); process.exit(1); }
console.log("ALL RTL CHECKS PASSED");
"""
    result = _run_node_js(harness)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL RTL CHECKS PASSED" in result.stdout


def test_value_cell_divider_uses_a_logical_rtl_safe_css_property() -> None:
    """The divider between adjacent .value cells must use the logical
    `border-inline-start` (mirrors correctly under RTL) instead of the
    physical `border-left` it used before - static source check, no
    Node.js needed."""
    content = CARD_PATH.read_text(encoding="utf-8")
    assert ".value+.value{border-inline-start:" in content
    assert ".value+.value{border-left:" not in content


@pytest.mark.skipif(NODE_BIN is None, reason="no local Node.js runtime available")
def test_two_decimal_precision_group() -> None:
    """weight, bone, fat_free_weight, body_fat_mass, body_water_mass and
    protein_mass show at most 2 decimals, with unnecessary trailing zeros
    dropped (minimumFractionDigits: 0)."""
    cases = [
        [94.75, "kg", "weight", "94,75 kg"],
        [25.00, "kg", "weight", "25 kg"],
        [67.10, "kg", "bone", "67,1 kg"],
        [1.005, "kg", "fat_free_weight", "1,01 kg"],
        [12.345, "kg", "body_fat_mass", "12,35 kg"],
        [0, "kg", "body_water_mass", "0 kg"],
        [3.5, "kg", "protein_mass", "3,5 kg"],
    ]
    result = _run_node_js(_FORMAT_JS_HARNESS.replace("CASES", json.dumps(cases)))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL FORMAT CHECKS PASSED" in result.stdout


@pytest.mark.skipif(NODE_BIN is None, reason="no local Node.js runtime available")
def test_one_decimal_precision_group() -> None:
    """bmi, bodyfat, water, muscle, protein, subfat and score show at most 1
    decimal, with unnecessary trailing zeros dropped."""
    cases = [
        [67.10, "", "bmi", "67,1"],
        [25.00, "%", "bodyfat", "25 %"],
        [50.5, "%", "water", "50,5 %"],
        [33.33, "%", "muscle", "33,3 %"],
        [18.0, "%", "protein", "18 %"],
        [12.34, "%", "subfat", "12,3 %"],
        [8.5, "", "score", "8,5"],
    ]
    result = _run_node_js(_FORMAT_JS_HARNESS.replace("CASES", json.dumps(cases)))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL FORMAT CHECKS PASSED" in result.stdout


@pytest.mark.skipif(NODE_BIN is None, reason="no local Node.js runtime available")
def test_zero_decimal_precision_group_and_dutch_thousands_separator() -> None:
    """bmr shows 0 decimals, and Dutch locale groups thousands with a dot."""
    cases = [
        [1818.0, "kcal", "bmr", "1.818 kcal"],
        [999, "kcal", "bmr", "999 kcal"],
        [1818.6, "kcal", "bmr", "1.819 kcal"],
    ]
    result = _run_node_js(_FORMAT_JS_HARNESS.replace("CASES", json.dumps(cases)))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL FORMAT CHECKS PASSED" in result.stdout


@pytest.mark.skipif(NODE_BIN is None, reason="no local Node.js runtime available")
def test_negative_and_missing_values_are_formatted_correctly() -> None:
    cases = [
        [-5.5, "kg", "weight", "-5,5 kg"],
        [-1818.0, "kcal", "bmr", "-1.818 kcal"],
        ["not-a-number", "kg", "weight", "—"],
    ]
    result = _run_node_js(_FORMAT_JS_HARNESS.replace("CASES", json.dumps(cases)))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL FORMAT CHECKS PASSED" in result.stdout


@pytest.mark.skipif(NODE_BIN is None, reason="no local Node.js runtime available")
def test_missing_and_falsy_edge_cases_never_show_as_a_real_zero() -> None:
    """Number(null), Number(""), Number("   ") and Number(false) all equal 0
    in JavaScript, and Number(true) equals 1 - none of these represent an
    actual measurement. format() must special-case them to the placeholder
    dash before ever calling Number(...), while a genuine numeric (or
    numeric-string) zero must still render as "0", not be swallowed."""
    harness = (
        _LOAD_CARD_JS_PRELUDE
        + r"""
const cases = [
  [undefined, "—"],
  [null, "—"],
  ["", "—"],
  ["   ", "—"],
  [true, "—"],
  [false, "—"],
  [0, "0"],
  ["0", "0"],
];
const dutchHass = { locale: { language: "nl", number_format: "language" } };
const failures = [];
for (const [value, expected] of cases) {
  const actual = Card.prototype.format.call({ _hass: dutchHass }, value, "", "weight");
  if (actual !== expected) {
    failures.push(`format(${JSON.stringify(value)}) = ${JSON.stringify(actual)}, expected ${JSON.stringify(expected)}`);
  }
}
if (failures.length) { console.error(failures.join("\n")); process.exit(1); }
console.log("ALL FORMAT CHECKS PASSED");
"""
    )
    result = _run_node_js(harness)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL FORMAT CHECKS PASSED" in result.stdout


def test_frontend_module_does_not_import_add_extra_js_url() -> None:
    """The Lovelace resource is now the one and only automatic loading
    route; add_extra_js_url must not also be used for the same card, or the
    browser would download fitage-card.js twice."""
    import custom_components.fitage.frontend as frontend_module

    assert not hasattr(frontend_module, "add_extra_js_url")


def test_production_code_never_reads_the_card_file_for_its_version() -> None:
    """CARD_VERSION must be a plain constant, not something derived from
    reading www/fitage-card.js at setup time - Path.read_text/Path.open are
    blocking calls Home Assistant's block_async_io flags when awaited from
    the event loop (custom_components/fitage/frontend.py used to call
    card_path.read_text() directly inside async_register_frontend)."""
    import inspect

    import custom_components.fitage.frontend as frontend_module

    source = inspect.getsource(frontend_module)
    assert "read_text(" not in source
    assert "read_bytes(" not in source
    assert ".open(" not in source
    assert re.search(r"(?<!\.)\bopen\(", source) is None


@run_async
async def test_static_path_registered_once_with_the_bundled_card() -> None:
    hass, _resources = storage_lovelace_data()
    with patch("homeassistant.helpers.storage.Store.async_delay_save"):
        await async_register_frontend(hass)
    hass.http.async_register_static_paths.assert_awaited_once()
    (configs,), _ = hass.http.async_register_static_paths.call_args
    assert len(configs) == 1
    assert configs[0].url_path == STATIC_URL_PATH
    assert configs[0].path == str(CARD_PATH)


@run_async
async def test_no_existing_resource_creates_exactly_one_module_resource() -> None:
    hass, resources = storage_lovelace_data()
    with patch("homeassistant.helpers.storage.Store.async_delay_save"):
        await async_register_frontend(hass)
    items = resources.async_items()
    assert len(items) == 1
    assert items[0]["url"] == MODULE_URL
    assert items[0]["type"] == "module"


@run_async
async def test_exact_resource_already_present_is_left_untouched() -> None:
    hass, resources = storage_lovelace_data(
        {"fitage-id": {"id": "fitage-id", "type": "module", "url": MODULE_URL}}
    )
    with patch("homeassistant.helpers.storage.Store.async_delay_save") as delay_save:
        await async_register_frontend(hass)
    delay_save.assert_not_called()
    assert resources.async_items() == [
        {"id": "fitage-id", "type": "module", "url": MODULE_URL}
    ]


@run_async
async def test_older_integrated_version_is_updated_in_place() -> None:
    hass, resources = storage_lovelace_data(
        {
            "fitage-id": {
                "id": "fitage-id",
                "type": "module",
                "url": "/fitage/fitage-card.js?v=0.4.0",
            }
        }
    )
    with patch("homeassistant.helpers.storage.Store.async_delay_save"):
        await async_register_frontend(hass)
    items = resources.async_items()
    assert len(items) == 1
    assert items[0]["id"] == "fitage-id"
    assert items[0]["url"] == MODULE_URL


@run_async
async def test_resource_updates_from_v0_6_3_to_v0_6_4() -> None:
    """The real-world upgrade this release ships: the previously-registered
    v0.6.3 Lovelace resource must update in place to v0.6.4, not duplicate."""
    hass, resources = storage_lovelace_data(
        {
            "fitage-id": {
                "id": "fitage-id",
                "type": "module",
                "url": "/fitage/fitage-card.js?v=0.6.3",
            }
        }
    )
    with patch("homeassistant.helpers.storage.Store.async_delay_save"):
        await async_register_frontend(hass)
    items = resources.async_items()
    assert len(items) == 1
    assert items[0]["id"] == "fitage-id"
    assert items[0]["url"] == "/fitage/fitage-card.js?v=0.6.4"
    assert items[0]["url"] == MODULE_URL


@run_async
async def test_old_manual_prototype_resource_is_never_modified() -> None:
    hass, resources = storage_lovelace_data(
        {
            "legacy-id": {
                "id": "legacy-id",
                "type": "module",
                "url": f"{LEGACY_PROTOTYPE_URL_PATH}?v=0.4.0",
            }
        }
    )
    with patch("homeassistant.helpers.storage.Store.async_delay_save"):
        await async_register_frontend(hass)
    items = {item["id"]: item for item in resources.async_items()}
    assert items["legacy-id"]["url"] == f"{LEGACY_PROTOTYPE_URL_PATH}?v=0.4.0"
    assert any(item["url"] == MODULE_URL for item in items.values())


@run_async
async def test_old_manual_prototype_resource_logs_a_clear_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    hass, _resources = storage_lovelace_data(
        {
            "legacy-id": {
                "id": "legacy-id",
                "type": "module",
                "url": f"{LEGACY_PROTOTYPE_URL_PATH}?v=0.4.0",
            }
        }
    )
    with patch("homeassistant.helpers.storage.Store.async_delay_save"):
        await async_register_frontend(hass)
    assert LEGACY_PROTOTYPE_URL_PATH in caplog.text
    assert "remove" in caplog.text.lower()


@run_async
async def test_unrelated_resources_are_never_touched() -> None:
    hass, resources = storage_lovelace_data(
        {
            "other-id": {
                "id": "other-id",
                "type": "js",
                "url": "/local/some-other-card.js?v=1",
            }
        }
    )
    with patch("homeassistant.helpers.storage.Store.async_delay_save"):
        await async_register_frontend(hass)
    items = {item["id"]: item for item in resources.async_items()}
    assert items["other-id"] == {
        "id": "other-id",
        "type": "js",
        "url": "/local/some-other-card.js?v=1",
    }
    assert len(items) == 2


@run_async
async def test_multiple_config_entries_do_not_cause_double_registration() -> None:
    """Simulates two FITAGE config entries both triggering setup on one hass."""
    hass, resources = storage_lovelace_data()
    with patch("homeassistant.helpers.storage.Store.async_delay_save"):
        await async_setup(hass, {})
        await async_setup(hass, {})
    assert len(resources.async_items()) == 1
    hass.http.async_register_static_paths.assert_awaited_once()


@run_async
async def test_config_entry_reload_does_not_cause_double_registration() -> None:
    hass, resources = storage_lovelace_data()
    with patch("homeassistant.helpers.storage.Store.async_delay_save"):
        await async_register_frontend(hass)
        # A reload only re-runs async_setup_entry, never the domain async_setup,
        # but registration must stay idempotent even if it were invoked again.
        await async_register_frontend(hass)
    assert len(resources.async_items()) == 1


@run_async
async def test_yaml_resource_mode_is_handled_safely_without_touching_files(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from homeassistant.components.lovelace import LovelaceData
    from homeassistant.components.lovelace.const import LOVELACE_DATA, MODE_YAML
    from homeassistant.components.lovelace.resources import ResourceYAMLCollection

    hass = fake_hass()
    hass.data[LOVELACE_DATA] = LovelaceData(
        resource_mode=MODE_YAML,
        dashboards={},
        resources=ResourceYAMLCollection([]),
        yaml_dashboards={},
    )
    with patch("homeassistant.helpers.storage.Store") as store:
        result = await async_setup(hass, {})
    assert result is True
    store.assert_not_called()
    assert "yaml" in caplog.text.lower()
    assert MODULE_URL in caplog.text


@run_async
async def test_lovelace_not_set_up_does_not_fail_integration_setup() -> None:
    hass = fake_hass()
    result = await async_setup(hass, {})
    assert result is True


@run_async
async def test_resource_registration_failure_does_not_fail_integration_setup(
    caplog: pytest.LogCaptureFixture,
) -> None:
    hass = fake_hass()
    with patch(
        "custom_components.fitage.frontend._async_register_lovelace_resource",
        side_effect=RuntimeError("boom"),
    ):
        result = await async_setup(hass, {})
    assert result is True
    assert "error" in caplog.text.lower() or "not" in caplog.text.lower()
    hass.http.async_register_static_paths.assert_awaited_once()


@run_async
async def test_missing_card_file_logs_a_warning_and_does_not_raise(
    caplog: pytest.LogCaptureFixture,
) -> None:
    hass = fake_hass()
    missing = Path("/nonexistent/fitage-card.js")
    with patch("custom_components.fitage.frontend._card_path", return_value=missing):
        await async_register_frontend(hass)
    assert "not found" in caplog.text
    hass.http.async_register_static_paths.assert_not_awaited()


@run_async
async def test_missing_card_file_does_not_fail_integration_setup() -> None:
    hass = fake_hass()
    missing = Path("/nonexistent/fitage-card.js")
    with patch("custom_components.fitage.frontend._card_path", return_value=missing):
        result = await async_setup(hass, {})
    assert result is True


@run_async
async def test_async_setup_registers_the_frontend_card() -> None:
    hass = fake_hass()
    with patch("custom_components.fitage.async_register_frontend") as register:
        register.return_value = None
        result = await async_setup(hass, {})
    register.assert_called_once_with(hass)
    assert result is True


@run_async
async def test_registration_never_writes_to_storage_directly() -> None:
    """No .storage file is ever read or written by our own code; only the
    already-loaded Home Assistant collection object is used."""
    hass, _resources = storage_lovelace_data()
    with patch("homeassistant.helpers.storage.Store") as store:
        await async_register_frontend(hass)
    store.assert_not_called()
