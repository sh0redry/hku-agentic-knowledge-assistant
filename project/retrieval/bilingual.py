from __future__ import annotations

from collections import OrderedDict


TERM_EXPANSIONS = {
    "学院": "HKU faculties departments schools Faculty of Architecture Arts Business Economics Dentistry Education Engineering Law Medicine Science Social Sciences",
    "院系": "HKU faculties departments schools",
    "学部": "HKU faculties departments schools",
    "本科": "undergraduate programmes bachelor first degree admissions",
    "专业": "HKU undergraduate programmes curriculum majors study",
    "课程": "HKU undergraduate programmes programme list curriculum courses study",
    "申请": "admissions apply application requirements eligibility",
    "入学": "admissions entry requirements eligibility",
    "国际": "international qualifications non-JUPAS overseas applicants",
    "非本地": "studentlife non-local students information for non-local students visa entry permit arrival",
    "高考": "Mainland NJCEE Gao Kao admissions",
    "内地": "Mainland China NJCEE Gao Kao admissions",
    "英语": "English language requirement IELTS TOEFL",
    "语言": "English language requirement IELTS TOEFL",
    "学费": "tuition fees composition fee living expenses",
    "费用": "tuition fees living expenses cost",
    "奖学金": "scholarships entrance scholarships admissions scholarships HKU entrance scholarships financial assistance",
    "资助": "financial assistance funding scholarships",
    "宿舍": "housing residence accommodation hall residence application",
    "住宿": "housing residence accommodation hall residence application",
    "签证": "visa entry permit non-local students immigration studentlife",
    "入境": "visa entry permit arrival non-local students studentlife information for non-local students",
    "研究生": "postgraduate graduate school taught postgraduate research postgraduate",
    "硕士": "taught postgraduate master admissions",
    "授课型": "taught postgraduate TPG admissions",
    "研究型": "research postgraduate RPG graduate school",
    "博士": "research postgraduate PhD graduate school",
    "图书馆": "HKU Libraries library services",
    "无线": "WiFi wireless network HKU WiFi",
    "邮箱": "email calendar HKU Connect email services",
    "日历": "calendar academic dates regulations",
    "校历": "calendar academic dates regulations",
    "学生生活": "student life student resources CEDARS",
    "社团": "student societies student life",
    "特殊教育": "SEN support funding special educational needs",
}


SOURCE_ALIASES = {
    "faculties_departments": ["学院", "院系", "学院列表", "香港大学学院", "HKU faculties"],
    "admissions": ["申请", "入学", "录取", "本科申请", "研究生申请", "本科课程", "专业列表", "undergraduate programmes", "admissions", "apply"],
    "fees_scholarships": ["学费", "费用", "奖学金", "资助", "tuition", "fees", "scholarships"],
    "academic_regulations": ["校历", "手册", "规定", "课程规则", "calendar", "handbook", "regulations"],
    "visa_arrival": ["签证", "入境", "非本地学生", "来港", "studentlife", "information for non-local students", "visa", "entry permit", "non-local students"],
    "housing": ["宿舍", "住宿", "舍堂", "residence", "housing", "accommodation"],
    "student_life": ["学生生活", "社团", "校园生活", "student life", "student societies"],
    "student_support": ["SEN", "特殊教育", "学生支援", "support", "funding"],
    "it_services": ["WiFi", "无线网络", "邮箱", "电邮", "HKU Portal", "ITS"],
    "library": ["图书馆", "library", "HKU Libraries"],
}


SOURCE_ID_ALIASES = {
    "hku_faculties_departments": ["香港大学有哪些学院", "HKU faculties and departments"],
    "hku_admissions_our_faculties": ["港大本科有哪些学院", "HKU admissions faculties"],
    "hku_admissions_programmes": ["本科专业", "本科课程", "undergraduate programmes"],
    "hku_admissions_home": ["本科申请入口", "admissions home"],
    "hku_admissions_international": ["国际课程申请", "international qualifications"],
    "hku_admissions_english_requirement": ["英语要求", "English language requirement"],
    "hku_admissions_mainland": ["内地高考", "Mainland Gao Kao NJCEE"],
    "hku_student_life_non_local": ["非本地学生", "签证入境", "non-local students"],
    "hku_cedars_housing": ["宿舍申请", "student housing"],
    "hku_cedars_residence_application": ["宿舍申请", "residence application"],
}


def has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def expand_query(query: str, *, category: str | None = None) -> list[str]:
    expansions = [query]
    matched_terms = [english for chinese, english in TERM_EXPANSIONS.items() if chinese in query]
    if matched_terms:
        expansions.append(" ".join(matched_terms))

    if category and category in SOURCE_ALIASES:
        expansions.append(" ".join(SOURCE_ALIASES[category]))

    return dedupe(expansions)


def expand_queries(queries: list[str], original_query: str | None = None) -> list[str]:
    expanded = []
    for query in queries:
        expanded.extend(expand_query(query))
    if original_query:
        expanded.extend(expand_query(original_query))
    return dedupe(expanded)


def aliases_for_source(source_id: str | None, category: str | None, title: str | None) -> list[str]:
    aliases = []
    if category:
        aliases.extend(SOURCE_ALIASES.get(category, []))
    if source_id:
        aliases.extend(SOURCE_ID_ALIASES.get(source_id, []))
    if title:
        aliases.append(title)
    return dedupe(aliases)


def aliases_markdown(aliases: list[str]) -> str:
    if not aliases:
        return ""
    return "## Search aliases\n\n" + ", ".join(aliases) + "\n\n"


def dedupe(items: list[str]) -> list[str]:
    ordered = OrderedDict()
    for item in items:
        normalized = " ".join(str(item).split())
        if normalized:
            ordered[normalized] = None
    return list(ordered.keys())
