import re

IOS_DEVICE_MAP = {
    # iPhone
    "iPhone1 1": "iPhone",
    "iPhone1 2": "iPhone 3G",
    "iPhone2 1": "iPhone 3GS",
    "iPhone3 1": "iPhone 4",
    "iPhone3 2": "iPhone 4",
    "iPhone3 3": "iPhone 4",
    "iPhone4 1": "iPhone 4S",
    "iPhone5 1": "iPhone 5",
    "iPhone5 2": "iPhone 5",
    "iPhone5 3": "iPhone 5c",
    "iPhone5 4": "iPhone 5c",
    "iPhone6 1": "iPhone 5s",
    "iPhone6 2": "iPhone 5s",
    "iPhone7 1": "iPhone 6 Plus",
    "iPhone7 2": "iPhone 6",
    "iPhone8 1": "iPhone 6s",
    "iPhone8 2": "iPhone 6s Plus",
    "iPhone8 4": "iPhone SE (第1代)",
    "iPhone9 1": "iPhone 7",
    "iPhone9 2": "iPhone 7 Plus",
    "iPhone9 3": "iPhone 7",
    "iPhone9 4": "iPhone 7 Plus",
    "iPhone10 1": "iPhone 8",
    "iPhone10 2": "iPhone 8 Plus",
    "iPhone10 3": "iPhone X",
    "iPhone10 4": "iPhone 8",
    "iPhone10 5": "iPhone 8 Plus",
    "iPhone10 6": "iPhone X",
    "iPhone11 2": "iPhone XS",
    "iPhone11 4": "iPhone XS Max",
    "iPhone11 6": "iPhone XS Max",
    "iPhone11 8": "iPhone XR",
    "iPhone12 1": "iPhone 11",
    "iPhone12 3": "iPhone 11 Pro",
    "iPhone12 5": "iPhone 11 Pro Max",
    "iPhone12 8": "iPhone SE (第2代)",
    "iPhone13 1": "iPhone 12 mini",
    "iPhone13 2": "iPhone 12",
    "iPhone13 3": "iPhone 12 Pro",
    "iPhone13 4": "iPhone 12 Pro Max",
    "iPhone14 2": "iPhone 13 Pro",
    "iPhone14 3": "iPhone 13 Pro Max",
    "iPhone14 4": "iPhone 13 mini",
    "iPhone14 5": "iPhone 13",
    "iPhone14 6": "iPhone SE (第3代)",
    "iPhone14 7": "iPhone 14",
    "iPhone14 8": "iPhone 14 Plus",
    "iPhone15 2": "iPhone 14 Pro",
    "iPhone15 3": "iPhone 14 Pro Max",
    "iPhone15 4": "iPhone 15",
    "iPhone15 5": "iPhone 15 Plus",
    "iPhone16 1": "iPhone 15 Pro",
    "iPhone16 2": "iPhone 15 Pro Max",
    "iPhone17 1": "iPhone 16 Pro",
    "iPhone17 2": "iPhone 16 Pro Max",
    "iPhone17 3": "iPhone 16",
    "iPhone17 4": "iPhone 16 Plus",
    "iPhone17 5": "iPhone 16e",
    "iPhone18 1": "iPhone 17 Pro",
    "iPhone18 2": "iPhone 17 Pro Max",
    "iPhone18 3": "iPhone 17",
    "iPhone18 4": "iPhone Air",
    "iPhone18 5": "iPhone 17e",

    # iPad（标准版）
    "iPad1 1": "iPad",
    "iPad2 1": "iPad 2",
    "iPad2 2": "iPad 2",
    "iPad2 3": "iPad 2",
    "iPad2 4": "iPad 2",
    "iPad3 1": "iPad 3",
    "iPad3 2": "iPad 3",
    "iPad3 3": "iPad 3",
    "iPad3 4": "iPad 4",
    "iPad3 5": "iPad 4",
    "iPad3 6": "iPad 4",
    "iPad6 11": "iPad 5",
    "iPad6 12": "iPad 5",
    "iPad7 5": "iPad 6",
    "iPad7 6": "iPad 6",
    "iPad7 11": "iPad 7",
    "iPad7 12": "iPad 7",
    "iPad11 6": "iPad 8",
    "iPad11 7": "iPad 8",
    "iPad12 1": "iPad 9",
    "iPad12 2": "iPad 9",
    "iPad13 18": "iPad 10",
    "iPad13 19": "iPad 10",
    "iPad15 7": "iPad (A16)",
    "iPad15 8": "iPad (A16)",

    # iPad Air
    "iPad4 1": "iPad Air",
    "iPad4 2": "iPad Air",
    "iPad4 3": "iPad Air",
    "iPad5 3": "iPad Air 2",
    "iPad5 4": "iPad Air 2",
    "iPad11 3": "iPad Air 3",
    "iPad11 4": "iPad Air 3",
    "iPad13 1": "iPad Air 4",
    "iPad13 2": "iPad Air 4",
    "iPad13 16": "iPad Air 5 (11-inch, M2)",
    "iPad13 17": "iPad Air 5 (13-inch, M2)",
    "iPad14 8": "iPad Air 6 (11-inch, M2)",
    "iPad14 9": "iPad Air 6 (11-inch, M2)",
    "iPad14 10": "iPad Air 6 (13-inch, M2)",
    "iPad14 11": "iPad Air 6 (13-inch, M2)",
    "iPad15 3": "iPad Air 7 (11-inch, M3)",
    "iPad15 4": "iPad Air 7 (11-inch, M3)",
    "iPad15 5": "iPad Air 7 (13-inch, M3)",
    "iPad15 6": "iPad Air 7 (13-inch, M3)",
    "iPad16 8": "iPad Air 8 (11-inch, M4)",
    "iPad16 9": "iPad Air 8 (11-inch, M4)",
    "iPad16 10": "iPad Air 8 (13-inch, M4)",
    "iPad16 11": "iPad Air 8 (13-inch, M4)",
    # iPad Pro
    "iPad6 3": "iPad Pro (9.7-inch)",
    "iPad6 4": "iPad Pro (9.7-inch)",
    "iPad6 7": "iPad Pro (12.9-inch)",
    "iPad6 8": "iPad Pro (12.9-inch)",
    "iPad7 1": "iPad Pro (12.9-inch, 第2代)",
    "iPad7 2": "iPad Pro (12.9-inch, 第2代)",
    "iPad7 3": "iPad Pro (10.5-inch, 第2代)",
    "iPad7 4": "iPad Pro (10.5-inch, 第2代)",
    "iPad8 1": "iPad Pro (11-inch, 第3代)",
    "iPad8 2": "iPad Pro (11-inch, 第3代)",
    "iPad8 3": "iPad Pro (11-inch, 第3代)",
    "iPad8 4": "iPad Pro (11-inch, 第3代)",
    "iPad8 5": "iPad Pro (12.9-inch, 第3代)",
    "iPad8 6": "iPad Pro (12.9-inch, 第3代)",
    "iPad8 7": "iPad Pro (12.9-inch, 第3代)",
    "iPad8 8": "iPad Pro (12.9-inch, 第3代)",
    "iPad8 9": "iPad Pro (11-inch, 第2代)",
    "iPad8 10": "iPad Pro (11-inch, 第2代)",
    "iPad8 11": "iPad Pro (12.9-inch, 第4代)",
    "iPad8 12": "iPad Pro (12.9-inch, 第4代)",
    "iPad13 4": "iPad Pro (11-inch, 第3代)",
    "iPad13 5": "iPad Pro (11-inch, 第3代)",
    "iPad13 6": "iPad Pro (11-inch, 第3代)",
    "iPad13 7": "iPad Pro (11-inch, 第3代)",
    "iPad13 8": "iPad Pro (12.9-inch, 第5代)",
    "iPad13 9": "iPad Pro (12.9-inch, 第5代)",
    "iPad13 10": "iPad Pro (12.9-inch, 第5代)",
    "iPad13 11": "iPad Pro (12.9-inch, 第5代)",
    "iPad14 3": "iPad Pro (11-inch, 第4代)",
    "iPad14 4": "iPad Pro (11-inch, 第4代)",
    "iPad14 5": "iPad Pro (12.9-inch, 第6代)",
    "iPad14 6": "iPad Pro (12.9-inch, 第6代)",
    "iPad16 3": "iPad Pro (11-inch, M4)",
    "iPad16 4": "iPad Pro (11-inch, M4)",
    "iPad16 5": "iPad Pro (13-inch, M4)",
    "iPad16 6": "iPad Pro (13-inch, M4)",
    "iPad17 1": "iPad Pro (11-inch, M5)",
    "iPad17 2": "iPad Pro (11-inch, M5)",
    "iPad18 1": "iPad Pro (13-inch, M5)",
    "iPad18 2": "iPad Pro (13-inch, M5)",

    # iPad mini
    "iPad2 5": "iPad mini",
    "iPad2 6": "iPad mini",
    "iPad2 7": "iPad mini",
    "iPad4 4": "iPad mini 2",
    "iPad4 5": "iPad mini 2",
    "iPad4 6": "iPad mini 2",
    "iPad4 7": "iPad mini 3",
    "iPad4 8": "iPad mini 3",
    "iPad4 9": "iPad mini 3",
    "iPad5 1": "iPad mini 4",
    "iPad5 2": "iPad mini 4",
    "iPad11 1": "iPad mini 5",
    "iPad11 2": "iPad mini 5",
    "iPad14 1": "iPad mini 6",
    "iPad14 2": "iPad mini 6",
    "iPad16 1": "iPad mini (A17 Pro)",
    "iPad16 2": "iPad mini (A17 Pro)",
}


def resolve_ios_device_name(device_code: str | None) -> str | None:
    """将 Apple 设备型号（如 iPad18 2）转为可读名称。"""
    if not device_code:
        return None

    code = device_code.strip()
    if not code:
        return None

    # 若客户端已传入完整名称（如 “iPad Pro (13-inch, M5) (iPad18,2)”），直接返回
    if "(" in code and ")" in code and any(prefix in code for prefix in ("iPad", "iPhone", "iPod")):
        return code

    # 支持从混合串中提取型号（如: "xxx (iPad18,2)" 或 "xxx (iPad18 2)"）
    m = re.search(r"(iPhone\d+[\s,]+\d+|iPad\d+[\s,]+\d+|iPod\d+[\s,]+\d+)", code)
    model_code = m.group(1) if m else code

    parsed = re.match(r"^(iPhone|iPad|iPod)\s*(\d+)[\s,]+(\d+)$", model_code)
    if parsed:
        prefix, major, minor = parsed.groups()
        code_space = f"{prefix}{major} {minor}"
        lookup_candidates = [model_code, code_space]
        display_code = code_space
    else:
        normalized = model_code.replace(",", " ")
        lookup_candidates = [model_code, normalized]
        display_code = normalized

    seen = set()
    for candidate in lookup_candidates:
        key = candidate.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        if key in IOS_DEVICE_MAP:
            return f"{IOS_DEVICE_MAP[key]} ({display_code})"

    # 兜底：符合 Apple 型号格式时按“型号(code)”返回，避免前端空白
    if parsed:
        return f"Apple设备 ({display_code})"

    return code
