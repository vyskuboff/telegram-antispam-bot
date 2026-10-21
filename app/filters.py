import re


def find_mixed_language_words(text):
    words = re.findall(r"\b\w+\b", text)
    result = []

    for w in words:
        if (
            re.search(r"[А-Яа-яЁё]", w)
            and re.search(r"[A-Za-z]", w)
        ):
            result.append(w)

    return result

def has_unicode_obfuscation(text):
    for ch in text:
        code = ord(ch)

        # combining characters
        if 0x0300 <= code <= 0x036F:
            return True

        # latin extended / phonetic / modifier letters
        if (
            0x1D00 <= code <= 0x1D7F or
            0x0250 <= code <= 0x02AF or
            0x1E00 <= code <= 0x1EFF
        ):
            return True

    return False

def has_emoji_spam(text, threshold_seq=6, threshold_total=10):
    seq = 0
    total = 0

    for ch in text:
        code = ord(ch)

        if (
            0x1F300 <= code <= 0x1FAFF or
            0x2600 <= code <= 0x26FF or
            0x2700 <= code <= 0x27BF
        ):
            seq += 1
            total += 1

            if seq >= threshold_seq or total >= threshold_total:
                return True
        else:
            seq = 0

    return False

def normalize_spaced_text(text):
    if len(text) < 10:
        return text

    space_ratio = text.count(" ") / max(len(text), 1)

    if space_ratio < 0.25:
        return text

    # collapse multiple spaces
    text = re.sub(r"\s+", " ", text)

    # detect if too many single-letter words
    words = text.split()
    single_char_words = [w for w in words if len(w) == 1]

    if len(single_char_words) < 5:
        return text

    # aggressive join of single letters
    joined = ""
    buffer = []

    for w in words:
        if len(w) == 1:
            buffer.append(w)
        else:
            if buffer:
                joined += "".join(buffer) + " "
                buffer = []
            joined += w + " "

    if buffer:
        joined += "".join(buffer)

    return joined.strip()

def has_spaced_spam_pattern(text):
    words = text.split()

    if len(words) < 8:
        return False

    single_char_words = [w for w in words if len(w) == 1]

    # More than 40% of words are single characters.
    if len(single_char_words) / len(words) > 0.4:
        return True

    return False


def spam_reason(text, stop_words):
    normalized = normalize_spaced_text(text)
    words = re.findall(r"\b\w+\b", normalized.lower())
    matches = [word for word in words if word in stop_words]
    if matches:
        return "Стоп-слова: " + ", ".join(matches[:10])
    if has_unicode_obfuscation(normalized):
        return "Unicode-обфускация текста"
    mixed = find_mixed_language_words(normalized)
    if mixed:
        return "Смешанные буквы: " + ", ".join(mixed[:10])
    if has_emoji_spam(normalized):
        return "Emoji-спам"
    if has_spaced_spam_pattern(text):
        return "Растянутый текст"
    return None
