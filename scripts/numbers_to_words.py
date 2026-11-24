r"""Write the numbers in narration texts as Telugu words, so the voice reads them the way a person would.

    python numbers_to_words.py --from 18            # dry run: lists every change in a report, changes nothing
    python numbers_to_words.py --from 18 --apply    # rewrites the pending sections, after backing them up

Only long videos numbered --from or higher, and only sections whose voice (voices\NN.mp3) does not exist yet, are
touched; a section that is already narrated keeps its text, so text and audio never disagree. Originals are copied to
D:\youtube\workflow\backups\numbers-<date>\<topic>\sections\NN.txt before a file is changed.

Rules: ordinary numbers, years (1954 -> పందొమ్మిది వందల యాభై నాలుగు), ordinals (19వ -> పందొమ్మిదవ), decimals
(2.4 -> రెండు పాయింట్ నాలుగు) and isotopes (కార్బన్-14 -> కార్బన్ పద్నాలుగు) become Telugu words. Names that are said
in English (5జీ, వైఫై 6, చంద్రయాన్-3, టీ4, బోయింగ్ 707) get English number words in Telugu script. OVERRIDES handles the
rest by exact text.
"""
import argparse
import datetime
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, r"D:\youtube\workflow\yt-workflow\scripts")
import topics  # noqa: E402

ONES = ["సున్నా", "ఒకటి", "రెండు", "మూడు", "నాలుగు", "ఐదు", "ఆరు", "ఏడు", "ఎనిమిది", "తొమ్మిది", "పది", "పదకొండు",
        "పన్నెండు", "పదమూడు", "పద్నాలుగు", "పదిహేను", "పదహారు", "పదిహేడు", "పద్దెనిమిది", "పందొమ్మిది"]
TENS = {2: "ఇరవై", 3: "ముప్పై", 4: "నలభై", 5: "యాభై", 6: "అరవై", 7: "డెబ్బై", 8: "ఎనభై", 9: "తొంభై"}
EN_ONES = ["జీరో", "వన్", "టూ", "త్రీ", "ఫోర్", "ఫైవ్", "సిక్స్", "సెవెన్", "ఎయిట్", "నైన్", "టెన్", "ఎలెవెన్", "ట్వెల్వ్",
           "థర్టీన్", "ఫోర్టీన్", "ఫిఫ్టీన్", "సిక్స్\u200cటీన్", "సెవెన్\u200cటీన్", "ఎయిటీన్", "నైన్\u200cటీన్"]
EN_TENS = {2: "ట్వంటీ", 3: "థర్టీ", 4: "ఫోర్టీ", 5: "ఫిఫ్టీ", 6: "సిక్స్టీ", 7: "సెవెంటీ", 8: "ఎయిటీ", 9: "నైంటీ"}

# exact text -> replacement, applied first (one-off cases the rules below would read wrongly)
OVERRIDES = {
    "18:04 గంటలకు": "సాయంత్రం ఆరు గంటల నాలుగు నిమిషాలకు",
    "1:1:3:1:1": "ఒకటి, ఒకటి, మూడు, ఒకటి, ఒకటి",
    "ఈ.28/39": "ఈ ట్వంటీ ఎయిట్ బై థర్టీ నైన్",
    "802.11": "ఎయిట్ ఓ టూ పాయింట్ ఎలెవెన్",
    "1310, 1550 నానోమీటర్ల": "వెయ్యి మూడు వందల పది, వెయ్యి ఐదు వందల యాభై నానోమీటర్ల",
    "హెచ్ఈ 178": "హెచ్ఈ వన్ సెవెంటీ ఎయిట్",
    "బోయింగ్ 707": "బోయింగ్ సెవెన్ ఓ సెవెన్",
    "123పే": "వన్ టూ త్రీ పే",
    "ఫోటో 51": "ఫోటో ఫిఫ్టీ వన్",
    "1900ల ": "పందొమ్మిది వందల ",                       # "1900ల ప్రారంభంలో": the early 1900s
    "2000ల ": "రెండు వేల ",
    "1800లలో": "పద్దెనిమిది వందలలో",
    "1900లలో": "పందొమ్మిది వందలలో",
}
ENGLISH_BEFORE = ("వైఫై", "బ్లూటూత్", "టైప్")       # "వైఫై 6" -> "వైఫై సిక్స్", "టైప్ 2" -> "టైప్ టూ"
ENGLISH_AFTER = ("జీ", "కె", "డీ")                  # "5జీ" -> "ఫైవ్ జీ"
MISSIONS = ("చంద్రయాన్", "మంగళయాన్", "గగన్\u200cయాన్", "ఆదిత్య", "అపోలో", "ఆర్టెమిస్", "వాయేజర్")
NOT_YEAR = ("నానో", "కోట్ల", "కోటి", "లక్ష", "బై", "పిక్సెల్", "మీటర్", "కిలో", "డిగ్రీ", "మెగా", "గిగా", "వాట్", "సార్లు",
            "రెట్లు", "కేజీ", "టన్ను", "మిల్లీ", "సెంటీ", "రూపాయ", "బీటీయూ", "అక్షర", "అడుగు", "మైళ్ల", "గ్రాము", "హెర్ట్జ్")
COUNTED = ("రోజు", "సంవత్సర", "ఏళ్ల", "గంట", "నిమిష", "సెకన్", "శాతం", "దేశాల", "మంది")   # "21 రోజులు" -> ఇరవై ఒక్క
TELUGU = re.compile(r"[\u0C00-\u0C7F]")
NUMBER = re.compile(r"(?<![\d.,])\d+(?:,\d+)*(?:\.\d+)?(?![\d])")


def below100(n: int) -> str:
    if n < 20:
        return ONES[n]
    t, o = divmod(n, 10)
    return TENS[t] + (f" {ONES[o]}" if o else "")


def below1000(n: int, final: bool) -> str:
    h, r = divmod(n, 100)
    if h == 0:
        return below100(r)
    if h == 1:
        return "వంద" if r == 0 else f"నూట {below100(r)}"
    return f"{ONES[h]} వందలు" if (r == 0 and final) else f"{ONES[h]} వందల" + (f" {below100(r)}" if r else "")


def cardinal(n: int, final: bool = True) -> str:
    """Indian grouping: కోటి, లక్ష, వెయ్యి. `final` picks వందలు/వేలు (end of a phrase) over వందల/వేల (before a word)."""
    if n < 1000:
        return below1000(n, final)
    for size, one, many_final, many in ((10 ** 7, "ఒక కోటి", "కోట్లు", "కోట్ల"), (10 ** 5, "ఒక లక్ష", "లక్షలు", "లక్షల"),
                                         (1000, "వెయ్యి", "వేలు", "వేల")):
        if n >= size:
            q, r = divmod(n, size)
            head = one if q == 1 else f"{cardinal(q, False)} {many_final if (r == 0 and final) else many}"
            return head + (f" {cardinal(r, final)}" if r else "")
    raise AssertionError(n)


def year(n: int, final: bool) -> str:
    """1100-1999 the way years are said: 1954 -> పందొమ్మిది వందల యాభై నాలుగు. Others as ordinary numbers."""
    if not 1100 <= n <= 1999:
        return cardinal(n, final)
    h, r = divmod(n, 100)
    if r == 0:
        return f"{below100(h)} వందలు" if final else f"{below100(h)} వందల"
    return f"{below100(h)} వందల {below100(r)}"


def ordinal(words: str) -> str:
    """Stem that the text's own "వ" completes: పందొమ్మిది -> పందొమ్మిద(వ), రెండు -> రెండ(వ), ఇరవై -> ఇరవయ్య(వ),
    వంద -> వంద(వ), ఒకటి -> ఒకట(వ)."""
    if words.endswith("ై"):
        return words[:-1] + "య్య"
    if words.endswith(("ు", "ి")):
        return words[:-1]
    return words


def english(n: int) -> str:
    if n < 20:
        return EN_ONES[n]
    if n < 100:
        t, o = divmod(n, 10)
        return EN_TENS[t] + (f" {EN_ONES[o]}" if o else "")
    return " ".join(EN_ONES[int(d)] for d in str(n))


def english_number(text: str) -> str:
    """'5' -> ఫైవ్, '5.0' -> ఫైవ్ పాయింట్ ఓ."""
    whole, _, frac = text.partition(".")
    words = english(int(whole))
    if frac:
        words += " పాయింట్ " + " ".join("ఓ" if d == "0" else EN_ONES[int(d)] for d in frac)
    return words


def telugu_number(text: str, after: str, before_word: str) -> str:
    """A number in Telugu words. `after` is the text right after it, `before_word` the word in front of it."""
    raw = text.replace(",", "")
    following = after.lstrip()
    final = not (after[:1].isspace() and TELUGU.match(following[:1] or " ")) and not TELUGU.match(after[:1] or " ")
    if "." in raw:
        whole, frac = raw.split(".")
        return f"{cardinal(int(whole))} పాయింట్ " + " ".join(ONES[int(d)] for d in frac)
    if len(raw) > 1 and raw.startswith("0"):                    # a code such as 0723: digit by digit
        return " ".join(ONES[int(d)] for d in raw)
    n = int(raw)
    if n == 1 and after[:1].isspace() and TELUGU.match(following[:1] or " "):
        return "ఒక"                                          # "1 సెంటీమీటర్" -> "ఒక సెంటీమీటర్"
    is_year = (len(raw) == 4 and "," not in text and 1100 <= n <= 1999
               and not following.startswith(NOT_YEAR) and before_word not in ("సుమారు", "దాదాపు", "బై"))
    if after.startswith("వ") and not after.startswith(("వంద", "వేల", "వేలు", "వరకు", "వద్ద")):   # ordinal: 19వ, 1905వ
        return ordinal(year(n, True) if is_year else cardinal(n, True))
    words = year(n, final) if is_year else cardinal(n, final)
    if (words.endswith(" ఒకటి") and len(raw) != 4 and after[:1].isspace()
            and following.startswith(tuple(u for u in NOT_YEAR if u != "బై") + COUNTED)):
        words = words[:-4] + "ఒక్క"                           # "41 డిగ్రీల" -> "నలభై ఒక్క డిగ్రీల"
    return words


def convert(text: str) -> str:
    for old, new in OVERRIDES.items():
        text = text.replace(old, new)
    text = english_names(text)
    # isotopes and other name-number pairs joined by a hyphen: Telugu words
    text = re.sub(r"([\u0C00-\u0C7F])-(\d+)", lambda m: f"{m.group(1)} {m.group(2)}", text)

    def replace(m):
        before = text[:m.start()].split()
        return telugu_number(m.group(), text[m.end():m.end() + 30], before[-1] if before else "")
    return NUMBER.sub(replace, text)


def english_names(text: str) -> str:
    """Numbers inside names that are said in English. A ZWNJ keeps "సిక్స్" + "లో" from fusing into one letter."""
    def joined(words, rest_start, source):
        return words + ("\u200c" if words.endswith("్") and TELUGU.match(source[rest_start:rest_start + 1] or " ") else "")
    text = re.sub(rf"({'|'.join(ENGLISH_BEFORE)}) (\d+(?:\.\d+)?)",
                  lambda m: f"{m.group(1)} " + joined(english_number(m.group(2)), m.end(), m.string), text)
    text = re.sub(rf"({'|'.join(MISSIONS)})[-\s]?(\d+)",
                  lambda m: f"{m.group(1)} " + joined(english(int(m.group(2))), m.end(), m.string), text)
    text = re.sub(rf"(?<![\d\u0C00-\u0C7F])(\d+)({'|'.join(ENGLISH_AFTER)})",
                  lambda m: f"{english(int(m.group(1)))} {m.group(2)}", text)
    # acronym glued to a number (టీ4, సీడీ4, డబ్ల్యూపీఏ2, పీ53, ఎల్1): English digits after a space
    return re.sub(r"([\u0C00-\u0C7F\u200c])(\d+)(?!\d|[.,]\d)",
                  lambda m: f"{m.group(1)} " + joined(english(int(m.group(2))), m.end(), m.string), text)

    def replace(m):
        before = text[:m.start()].split()
        return telugu_number(m.group(), text[m.end():m.end() + 30], before[-1] if before else "")
    return NUMBER.sub(replace, text)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--from", dest="first", type=int, default=18, help="first long video number")
    ap.add_argument("--apply", action="store_true", help="change the files (default: only report)")
    ap.add_argument("--report", default=str(Path(__file__).with_name("numbers_report.txt")))
    A = ap.parse_args()

    backup = Path(r"D:\youtube\workflow\backups") / f"numbers-{datetime.date.today():%Y-%m-%d}"
    lines, changed = [], 0
    for topic in topics.find_topics(("long",)):
        m = topics.ORDER_PREFIX.match(topic.name)
        if not m or int(m.group(1)) < A.first:
            continue
        for job in topics.pending_audio(topic):
            path = topic.path / "sections" / f"{job.number:02d}.txt"
            if not path.is_file():
                continue
            old = topics.read_text(path)
            new = convert(old)
            left = NUMBER.findall(new)
            if new == old and not left:
                continue
            changed += new != old
            lines.append(f"===== {topic.name} / sections/{path.name}" + (f"   DIGITS LEFT: {left}" if left else ""))
            for a, b in zip(old.splitlines(), new.splitlines()):
                if a != b:
                    lines += [f"  - {a}", f"  + {b}"]
            if A.apply and new != old:
                target = backup / topic.name / "sections" / path.name
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    shutil.copy2(path, target)
                path.write_text(new, encoding="utf-8-sig")
    Path(A.report).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{changed} section files {'changed' if A.apply else 'would change'}; report: {A.report}"
          + (f"; originals in {backup}" if A.apply else ""))


if __name__ == "__main__":
    main()
