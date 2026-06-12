"""Small in-module localization table for preference UI text."""

import locale

import bpy


LANGUAGE_AUTO = "AUTO"
FALLBACK_LANGUAGE = "en_US"

SUPPORTED_LANGUAGES = (
    ("zh_HANS", "简体中文"),
    ("zh_HANT", "繁體中文"),
    ("ja_JP", "日本語"),
    ("ko_KR", "한국어"),
    ("vi_VN", "Tiếng Việt"),
    ("th_TH", "ไทย"),
    ("hi_IN", "हिन्दी"),
    ("ar_EG", "العربية"),
)

LANGUAGE_ITEMS = (
    (LANGUAGE_AUTO, "自动 / Auto", "Follow system language"),
    *((language_id, label, "") for language_id, label in SUPPORTED_LANGUAGES),
)

SYSTEM_LOCALE_MAP = {
    "zh": "zh_HANS",
    "zh_cn": "zh_HANS",
    "zh_sg": "zh_HANS",
    "zh_hans": "zh_HANS",
    "zh_tw": "zh_HANT",
    "zh_hk": "zh_HANT",
    "zh_mo": "zh_HANT",
    "zh_hant": "zh_HANT",
    "ja": "ja_JP",
    "ko": "ko_KR",
    "vi": "vi_VN",
    "th": "th_TH",
    "hi": "hi_IN",
    "ar": "ar_EG",
}

MESSAGES = {
    "Language": {
        "en_US": "Language",
        "zh_HANS": "语言",
        "zh_HANT": "語言",
        "ja_JP": "言語",
        "ko_KR": "언어",
        "vi_VN": "Ngôn ngữ",
        "th_TH": "ภาษา",
        "hi_IN": "भाषा",
        "ar_EG": "اللغة",
    },
    "Candidate Box Position": {
        "en_US": "Candidate Box Position",
        "zh_HANS": "候选框位置",
        "zh_HANT": "候選框位置",
        "ja_JP": "候補ウィンドウの位置",
        "ko_KR": "후보 창 위치",
        "vi_VN": "Vị trí khung gợi ý",
        "th_TH": "ตำแหน่งหน้าต่างตัวเลือก",
        "hi_IN": "उम्मीदवार विंडो की स्थिति",
        "ar_EG": "موضع نافذة المرشحات",
    },
    "Pre-position Candidate Box": {
        "en_US": "Pre-position Candidate Box",
        "zh_HANS": "提前定位候选框",
        "zh_HANT": "提前定位候選框",
        "ja_JP": "候補ウィンドウを事前配置",
        "ko_KR": "후보 창 미리 배치",
        "vi_VN": "Đặt trước vị trí khung gợi ý",
        "th_TH": "จัดตำแหน่งหน้าต่างตัวเลือกล่วงหน้า",
        "hi_IN": "उम्मीदवार विंडो पहले से रखें",
        "ar_EG": "تحديد موضع نافذة المرشحات مسبقًا",
    },
    "Add Composition Character Offset": {
        "en_US": "Add Composition Character Offset",
        "zh_HANS": "叠加组合字符偏移",
        "zh_HANT": "疊加組合字元偏移",
        "ja_JP": "変換中の文字位置を加算",
        "ko_KR": "조합 문자 오프셋 추가",
        "vi_VN": "Thêm độ lệch ký tự đang ghép",
        "th_TH": "เพิ่มออฟเซ็ตอักขระที่กำลังประกอบ",
        "hi_IN": "संयोजन अक्षर ऑफ़सेट जोड़ें",
        "ar_EG": "إضافة إزاحة حرف التركيب",
    },
    "X Offset": {
        "en_US": "X Offset",
        "zh_HANS": "X 偏移",
        "zh_HANT": "X 偏移",
        "ja_JP": "X オフセット",
        "ko_KR": "X 오프셋",
        "vi_VN": "Độ lệch X",
        "th_TH": "ออฟเซ็ต X",
        "hi_IN": "X ऑफ़सेट",
        "ar_EG": "إزاحة X",
    },
    "Y Offset": {
        "en_US": "Y Offset",
        "zh_HANS": "Y 偏移",
        "zh_HANT": "Y 偏移",
        "ja_JP": "Y オフセット",
        "ko_KR": "Y 오프셋",
        "vi_VN": "Độ lệch Y",
        "th_TH": "ออฟเซ็ต Y",
        "hi_IN": "Y ऑफ़सेट",
        "ar_EG": "إزاحة Y",
    },
    "Input Mode": {
        "en_US": "Input Mode",
        "zh_HANS": "输入模式",
        "zh_HANT": "輸入模式",
        "ja_JP": "入力モード",
        "ko_KR": "입력 모드",
        "vi_VN": "Chế độ nhập",
        "th_TH": "โหมดป้อนข้อมูล",
        "hi_IN": "इनपुट मोड",
        "ar_EG": "وضع الإدخال",
    },
    "Shortcut IME Avoidance (Experimental)": {
        "en_US": "Shortcut IME Avoidance (Experimental)",
        "zh_HANS": "快捷键避让（实验）",
        "zh_HANT": "快捷鍵避讓（實驗）",
        "ja_JP": "ショートカットIME回避（実験）",
        "ko_KR": "단축키 IME 회피(실험)",
        "vi_VN": "Né IME phím tắt (thử nghiệm)",
        "th_TH": "หลีกเลี่ยง IME สำหรับปุ่มลัด (ทดลอง)",
        "hi_IN": "शॉर्टकट IME परिहार (प्रयोगात्मक)",
        "ar_EG": "تجنب IME للاختصارات (تجريبي)",
    },
    (
        "Temporarily close this window's IME state on shortcut-heavy "
        "surfaces; some IMEs may not work"
    ): {
        "en_US": (
            "Temporarily close this window's IME state on shortcut-heavy "
            "surfaces; some IMEs may not work"
        ),
        "zh_HANS": "在快捷键密集区域临时关闭当前窗口输入法状态；部分输入法可能无效。",
        "zh_HANT": "在快捷鍵密集區域暫時關閉目前視窗輸入法狀態；部分輸入法可能無效。",
        "ja_JP": (
            "ショートカット中心の領域では、このウィンドウのIME状態を一時的に"
            "閉じます。一部のIMEでは機能しない場合があります。"
        ),
        "ko_KR": (
            "단축키가 많은 영역에서 현재 창의 IME 상태를 임시로 닫습니다. "
            "일부 IME에서는 동작하지 않을 수 있습니다."
        ),
        "vi_VN": (
            "Tạm thời đóng trạng thái IME của cửa sổ này trên các vùng dùng "
            "nhiều phím tắt; một số IME có thể không hoạt động."
        ),
        "th_TH": (
            "ปิดสถานะ IME ของหน้าต่างนี้ชั่วคราวในพื้นที่ที่ใช้ปุ่มลัดเป็นหลัก; "
            "IME บางตัวอาจไม่ทำงาน"
        ),
        "hi_IN": (
            "शॉर्टकट-प्रधान क्षेत्रों में इस विंडो की IME स्थिति अस्थायी रूप "
            "से बंद करें; कुछ IME काम नहीं कर सकते।"
        ),
        "ar_EG": (
            "إغلاق حالة IME لهذه النافذة مؤقتًا في المناطق المعتمدة على "
            "الاختصارات؛ قد لا تعمل بعض طرق الإدخال."
        ),
    },
    "Candidate box X offset in screen pixels": {
        "en_US": "Candidate box X offset in screen pixels",
        "zh_HANS": "候选框 X 轴手动偏移，单位为屏幕像素",
        "zh_HANT": "候選框 X 軸手動偏移，單位為螢幕像素",
        "ja_JP": "候補ウィンドウの X 方向オフセット（画面ピクセル）",
        "ko_KR": "후보 창 X축 오프셋, 화면 픽셀 단위",
        "vi_VN": "Độ lệch X của khung gợi ý, tính bằng pixel màn hình",
        "th_TH": "ออฟเซ็ตแกน X ของหน้าต่างตัวเลือก หน่วยเป็นพิกเซลหน้าจอ",
        "hi_IN": "उम्मीदवार विंडो का X ऑफ़सेट, स्क्रीन पिक्सेल में",
        "ar_EG": "إزاحة X لنافذة المرشحات بوحدة بكسل الشاشة",
    },
    "Candidate box Y offset in screen pixels": {
        "en_US": "Candidate box Y offset in screen pixels",
        "zh_HANS": "候选框 Y 轴手动偏移，单位为屏幕像素",
        "zh_HANT": "候選框 Y 軸手動偏移，單位為螢幕像素",
        "ja_JP": "候補ウィンドウの Y 方向オフセット（画面ピクセル）",
        "ko_KR": "후보 창 Y축 오프셋, 화면 픽셀 단위",
        "vi_VN": "Độ lệch Y của khung gợi ý, tính bằng pixel màn hình",
        "th_TH": "ออฟเซ็ตแกน Y ของหน้าต่างตัวเลือก หน่วยเป็นพิกเซลหน้าจอ",
        "hi_IN": "उम्मीदवार विंडो का Y ऑफ़सेट, स्क्रीन पिक्सेल में",
        "ar_EG": "إزاحة Y لنافذة المرشحات بوحدة بكسل الشاشة",
    },
    "Move candidate box near the text cursor before composition": {
        "en_US": "Move candidate box near the text cursor before composition",
        "zh_HANS": "在进入文本编辑器和编辑器重绘时主动把 IME 候选框移动到光标附近",
        "zh_HANT": "進入文字編輯器與重繪時，主動將 IME 候選框移到游標附近",
        "ja_JP": "入力開始前に候補ウィンドウをテキストカーソル付近へ移動します",
        "ko_KR": "입력 전에 후보 창을 텍스트 커서 근처로 이동합니다",
        "vi_VN": "Di chuyển khung gợi ý đến gần con trỏ văn bản trước khi nhập",
        "th_TH": "ย้ายหน้าต่างตัวเลือกไปใกล้เคอร์เซอร์ข้อความก่อนเริ่มป้อน",
        "hi_IN": "इनपुट से पहले उम्मीदवार विंडो को टेक्स्ट कर्सर के पास ले जाएँ",
        "ar_EG": "ينقل نافذة المرشحات قرب مؤشر النص قبل الإدخال",
    },
    "Use IME requested composition character position as extra candidate offset": {
        "en_US": (
            "Use IME requested composition character position as extra "
            "candidate offset"
        ),
        "zh_HANS": "按输入法请求的组合字符串字符位置额外移动候选框",
        "zh_HANT": "依照輸入法請求的組合字串字元位置額外移動候選框",
        "ja_JP": "IME が要求する変換中の文字位置を候補位置の追加オフセットとして使います",
        "ko_KR": "IME가 요청한 조합 문자 위치를 후보 창 추가 오프셋으로 사용합니다",
        "vi_VN": "Dùng vị trí ký tự đang ghép do IME yêu cầu làm độ lệch bổ sung",
        "th_TH": "ใช้ตำแหน่งอักขระที่ IME ร้องขอเป็นออฟเซ็ตเพิ่มเติม",
        "hi_IN": (
            "IME द्वारा माँगी गई संयोजन अक्षर स्थिति को अतिरिक्त ऑफ़सेट के "
            "रूप में उपयोग करें"
        ),
        "ar_EG": "استخدم موضع حرف التركيب الذي يطلبه IME كإزاحة إضافية",
    },
}


def normalized_language(language_id: str | None) -> str:
    """Collapse Blender and OS locale names into the languages we ship."""
    if not language_id:
        return FALLBACK_LANGUAGE
    language_id = language_id.lower().replace("-", "_")
    if language_id in SYSTEM_LOCALE_MAP:
        return SYSTEM_LOCALE_MAP[language_id]
    prefix = language_id.split("_", 1)[0]
    return SYSTEM_LOCALE_MAP.get(prefix, FALLBACK_LANGUAGE)


def blender_language() -> str | None:
    """Blender's DEFAULT value means the OS locale should decide."""
    try:
        language_id = bpy.context.preferences.view.language
    except (AttributeError, ReferenceError, RuntimeError):
        return None
    if not language_id or language_id == "DEFAULT":
        return None
    return language_id


def locale_language() -> str | None:
    """System locale probing can fail, especially on unusual setups."""
    try:
        language_id, _encoding = locale.getlocale()
    except (TypeError, ValueError):
        return None
    return language_id


def system_language() -> str:
    """Prefer Blender's explicit language, then fall back to the OS locale."""
    return normalized_language(blender_language() or locale_language())


def selected_language(preferences: object = None) -> str:
    """Resolve the Auto sentinel stored in preferences."""
    language_id = getattr(preferences, "ime_bridge_language", LANGUAGE_AUTO)
    if language_id == LANGUAGE_AUTO:
        return system_language()
    return language_id


def text(message: str, preferences: object = None) -> str:
    """Use the requested translation, then English, then the original key."""
    language_id = selected_language(preferences)
    return MESSAGES.get(message, {}).get(
        language_id,
        MESSAGES.get(message, {}).get(FALLBACK_LANGUAGE, message),
    )


def build_translation_dict() -> dict[str, dict[tuple[str, str], str]]:
    """Blender wants translations keyed by context/message tuples."""
    dictionary = {}
    for message, translations in MESSAGES.items():
        for language_id, translated in translations.items():
            if language_id == FALLBACK_LANGUAGE:
                continue
            dictionary.setdefault(language_id, {})[("*", message)] = translated
    return dictionary


def register() -> None:
    """Reload-friendly registration: clear the old table before adding ours."""
    unregister()
    bpy.app.translations.register(__name__, build_translation_dict())


def unregister() -> None:
    """Missing translation tables are normal during failed setup and reloads."""
    try:
        bpy.app.translations.unregister(__name__)
    except (KeyError, RuntimeError, ValueError):
        return
