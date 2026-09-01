"""
src/job_radar/taxonomy/isco.py

Global Occupation Taxonomy based on the International Standard Classification of Occupations (ISCO-08),
with crosswalk mappings to:
  - ANZSCO (Australian and New Zealand Standard Classification of Occupations)
  - NOC 2021 (National Occupational Classification - Canada)
  - O*NET-SOC 2019 (US Standard Occupational Classification)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass(frozen=True)
class ISCOUnitGroup:
    """A 4-digit ISCO-08 Unit Group."""
    code: str
    title: str
    major_group_code: str
    major_group_title: str
    sub_major_code: str
    sub_major_title: str
    minor_group_code: str
    minor_group_title: str
    keywords: Tuple[str, ...]
    anzsco_codes: Tuple[str, ...] = ()
    noc_codes: Tuple[str, ...] = ()
    onet_soc_codes: Tuple[str, ...] = ()


# 10 ISCO-08 Major Groups
ISCO_MAJOR_GROUPS: Dict[str, str] = {
    "1": "Managers",
    "2": "Professionals",
    "3": "Technicians and Associate Professionals",
    "4": "Clerical Support Workers",
    "5": "Services and Sales Workers",
    "6": "Skilled Agricultural, Forestry and Fishery Workers",
    "7": "Craft and Related Trades Workers",
    "8": "Plant and Machine Operators and Assemblers",
    "9": "Elementary Occupations",
    "0": "Armed Forces Occupations",
}

# Key Sub-Major Groups
ISCO_SUB_MAJOR_GROUPS: Dict[str, str] = {
    "11": "Chief Executives, Senior Officials and Legislators",
    "12": "Administrative and Commercial Managers",
    "13": "Production and Specialized Services Managers",
    "14": "Hospitality, Retail and Other Services Managers",
    "21": "Science and Engineering Professionals",
    "22": "Health Professionals",
    "23": "Teaching Professionals",
    "24": "Business and Administration Professionals",
    "25": "Information and Communications Technology Professionals",
    "26": "Legal, Social and Cultural Professionals",
    "31": "Science and Engineering Associate Professionals",
    "32": "Health Associate Professionals",
    "33": "Business and Administration Associate Professionals",
    "34": "Legal, Social, Cultural and Related Associate Professionals",
    "35": "Information and Communications Technicians",
    "41": "General and Keyboard Clerks",
    "42": "Customer Services Clerks",
    "43": "Numerical and Material Recording Clerks",
    "44": "Other Clerical Support Workers",
    "51": "Personal Services Workers",
    "52": "Sales Workers",
    "53": "Personal Care Workers",
    "54": "Protective Services Workers",
    "61": "Market-oriented Skilled Agricultural Workers",
    "62": "Market-oriented Skilled Forestry, Fishery and Hunting Workers",
    "71": "Building and Related Trades Workers (excluding Electricians)",
    "72": "Metal, Machinery and Related Trades Workers",
    "73": "Handicraft and Printing Workers",
    "74": "Electrical and Electronic Trades Workers",
    "75": "Food Processing, Woodworking, Garment and Other Craft Workers",
    "81": "Stationary Plant and Machine Operators",
    "82": "Assemblers",
    "83": "Drivers and Mobile Plant Operators",
    "91": "Cleaners and Helpers",
    "92": "Agricultural, Forestry and Fishery Labourers",
    "93": "Labourers in Mining, Construction, Manufacturing and Transport",
    "94": "Food Preparation Assistants",
    "95": "Street and Related Sales and Service Workers",
    "96": "Refuse Workers and Other Elementary Workers",
}

# Comprehensive unit groups with crosswalks spanning all major labor-mobility sectors
ISCO_UNIT_GROUPS: Dict[str, ISCOUnitGroup] = {
    # --- Healthcare (Major Group 2 & 3) ---
    "2211": ISCOUnitGroup(
        code="2211",
        title="Generalist Medical Practitioners",
        major_group_code="2",
        major_group_title="Professionals",
        sub_major_code="22",
        sub_major_title="Health Professionals",
        minor_group_code="221",
        minor_group_title="Medical Doctors",
        keywords=("general practitioner", "gp", "family physician", "primary care doctor", "medical officer", "physician"),
        anzsco_codes=("253111",),
        noc_codes=("31102",),
        onet_soc_codes=("29-1215.00",),
    ),
    "2212": ISCOUnitGroup(
        code="2212",
        title="Specialist Medical Practitioners",
        major_group_code="2",
        major_group_title="Professionals",
        sub_major_code="22",
        sub_major_title="Health Professionals",
        minor_group_code="221",
        minor_group_title="Medical Doctors",
        keywords=("cardiologist", "surgeon", "radiologist", "anesthesiologist", "pediatrician", "oncologist", "neurologist", "psychiatrist", "pathologist", "dermatologist"),
        anzsco_codes=("253999", "253511", "253311"),
        noc_codes=("31100", "31101"),
        onet_soc_codes=("29-1228.00", "29-1240.00"),
    ),
    "2221": ISCOUnitGroup(
        code="2221",
        title="Nursing Professionals",
        major_group_code="2",
        major_group_title="Professionals",
        sub_major_code="22",
        sub_major_title="Health Professionals",
        minor_group_code="222",
        minor_group_title="Nursing and Midwifery Professionals",
        keywords=("registered nurse", "rn", "staff nurse", "clinical nurse", "icu nurse", "surgical nurse", "nurse practitioner", "charge nurse", "infirmière", "krankenschwester"),
        anzsco_codes=("254411", "254415", "254418", "254422"),
        noc_codes=("31301", "31300"),
        onet_soc_codes=("29-1141.00", "29-1171.00"),
    ),
    "2261": ISCOUnitGroup(
        code="2261",
        title="Dentists",
        major_group_code="2",
        major_group_title="Professionals",
        sub_major_code="22",
        sub_major_title="Health Professionals",
        minor_group_code="226",
        minor_group_title="Other Health Professionals",
        keywords=("dentist", "dental surgeon", "orthodontist", "periodontist", "oral surgeon"),
        anzsco_codes=("252312",),
        noc_codes=("31110",),
        onet_soc_codes=("29-1021.00",),
    ),
    "2262": ISCOUnitGroup(
        code="2262",
        title="Pharmacists",
        major_group_code="2",
        major_group_title="Professionals",
        sub_major_code="22",
        sub_major_title="Health Professionals",
        minor_group_code="226",
        minor_group_title="Other Health Professionals",
        keywords=("pharmacist", "clinical pharmacist", "hospital pharmacist", "dispensing pharmacist", "apotheker"),
        anzsco_codes=("251511", "251513"),
        noc_codes=("31120",),
        onet_soc_codes=("29-1051.00",),
    ),
    "2264": ISCOUnitGroup(
        code="2264",
        title="Physiotherapists",
        major_group_code="2",
        major_group_title="Professionals",
        sub_major_code="22",
        sub_major_title="Health Professionals",
        minor_group_code="226",
        minor_group_title="Other Health Professionals",
        keywords=("physiotherapist", "physical therapist", "pt", "kinesiologist"),
        anzsco_codes=("252511",),
        noc_codes=("31202",),
        onet_soc_codes=("29-1123.00",),
    ),

    # --- Engineering & Science (Sub-Major 21) ---
    "2141": ISCOUnitGroup(
        code="2141",
        title="Industrial and Production Engineers",
        major_group_code="2",
        major_group_title="Professionals",
        sub_major_code="21",
        sub_major_title="Science and Engineering Professionals",
        minor_group_code="214",
        minor_group_title="Engineering Professionals (excluding Electrotechnology)",
        keywords=("industrial engineer", "production engineer", "process engineer", "manufacturing engineer", "quality engineer", "supply chain engineer"),
        anzsco_codes=("233511", "233513"),
        noc_codes=("21301",),
        onet_soc_codes=("17-2112.00",),
    ),
    "2142": ISCOUnitGroup(
        code="2142",
        title="Civil Engineers",
        major_group_code="2",
        major_group_title="Professionals",
        sub_major_code="21",
        sub_major_title="Science and Engineering Professionals",
        minor_group_code="214",
        minor_group_title="Engineering Professionals (excluding Electrotechnology)",
        keywords=("civil engineer", "structural engineer", "geotechnical engineer", "site engineer", "construction engineer", "transportation engineer", "bridge engineer"),
        anzsco_codes=("233211", "233214", "233215"),
        noc_codes=("21300",),
        onet_soc_codes=("17-2051.00",),
    ),
    "2144": ISCOUnitGroup(
        code="2144",
        title="Mechanical Engineers",
        major_group_code="2",
        major_group_title="Professionals",
        sub_major_code="21",
        sub_major_title="Science and Engineering Professionals",
        minor_group_code="214",
        minor_group_title="Engineering Professionals (excluding Electrotechnology)",
        keywords=("mechanical engineer", "hvac engineer", "automotive engineer", "robotics mechanical engineer", "thermal engineer", "fluid dynamics engineer", "piping engineer"),
        anzsco_codes=("233512",),
        noc_codes=("21301",),
        onet_soc_codes=("17-2141.00",),
    ),
    "2145": ISCOUnitGroup(
        code="2145",
        title="Chemical Engineers",
        major_group_code="2",
        major_group_title="Professionals",
        sub_major_code="21",
        sub_major_title="Science and Engineering Professionals",
        minor_group_code="214",
        minor_group_title="Engineering Professionals (excluding Electrotechnology)",
        keywords=("chemical engineer", "process design engineer", "biochemical engineer", "refinery engineer", "polymers engineer"),
        anzsco_codes=("233111",),
        noc_codes=("21303",),
        onet_soc_codes=("17-2041.00",),
    ),
    "2146": ISCOUnitGroup(
        code="2146",
        title="Mining, Metallurgical and Petroleum Engineers",
        major_group_code="2",
        major_group_title="Professionals",
        sub_major_code="21",
        sub_major_title="Science and Engineering Professionals",
        minor_group_code="214",
        minor_group_title="Engineering Professionals (excluding Electrotechnology)",
        keywords=("petroleum engineer", "drilling engineer", "reservoir engineer", "mining engineer", "metallurgical engineer", "subsea engineer", "sondage pétrolier", "mud engineer"),
        anzsco_codes=("233611", "233612"),
        noc_codes=("21302", "21310"),
        onet_soc_codes=("17-2171.00", "17-2151.00"),
    ),
    "2151": ISCOUnitGroup(
        code="2151",
        title="Electrical Engineers",
        major_group_code="2",
        major_group_title="Professionals",
        sub_major_code="21",
        sub_major_title="Science and Engineering Professionals",
        minor_group_code="215",
        minor_group_title="Electrotechnology Engineers",
        keywords=("electrical engineer", "power systems engineer", "grid engineer", "high voltage engineer", "substation engineer", "electronics design engineer"),
        anzsco_codes=("233311",),
        noc_codes=("21310",),
        onet_soc_codes=("17-2071.00",),
    ),

    # --- Information and Communications Technology (Sub-Major 25) ---
    "2511": ISCOUnitGroup(
        code="2511",
        title="Systems Analysts",
        major_group_code="2",
        major_group_title="Professionals",
        sub_major_code="25",
        sub_major_title="Information and Communications Technology Professionals",
        minor_group_code="251",
        minor_group_title="Software and Applications Developers and Analysts",
        keywords=("systems analyst", "business systems analyst", "it systems architect", "enterprise architect", "it solution architect"),
        anzsco_codes=("261112",),
        noc_codes=("21221",),
        onet_soc_codes=("15-1211.00",),
    ),
    "2512": ISCOUnitGroup(
        code="2512",
        title="Software Developers",
        major_group_code="2",
        major_group_title="Professionals",
        sub_major_code="25",
        sub_major_title="Information and Communications Technology Professionals",
        minor_group_code="251",
        minor_group_title="Software and Applications Developers and Analysts",
        keywords=("software engineer", "software developer", "fullstack developer", "fullstack engineer", "backend engineer", "backend developer", "frontend engineer", "frontend developer", "mobile developer", "mobile engineer", "android engineer", "android developer", "ios developer", "ios engineer", "flutter developer", "flutter engineer", "devops engineer", "cloud architect", "site reliability engineer", "sre", "kotlin developer"),
        anzsco_codes=("261312", "261313"),
        noc_codes=("21232", "21230"),
        onet_soc_codes=("15-1252.00", "15-1254.00"),
    ),
    "2514": ISCOUnitGroup(
        code="2514",
        title="Applications Programmers",
        major_group_code="2",
        major_group_title="Professionals",
        sub_major_code="25",
        sub_major_title="Information and Communications Technology Professionals",
        minor_group_code="251",
        minor_group_title="Software and Applications Developers and Analysts",
        keywords=("programmer", "application developer", "python programmer", "java developer", "c++ developer", "embedded software developer"),
        anzsco_codes=("261311",),
        noc_codes=("21230",),
        onet_soc_codes=("15-1251.00",),
    ),
    "2519": ISCOUnitGroup(
        code="2519",
        title="Software and Applications Developers and Analysts Not Elsewhere Classified",
        major_group_code="2",
        major_group_title="Professionals",
        sub_major_code="25",
        sub_major_title="Information and Communications Technology Professionals",
        minor_group_code="251",
        minor_group_title="Software and Applications Developers and Analysts",
        keywords=("ai engineer", "machine learning engineer", "ml engineer", "data scientist", "data science", "llm engineer", "ai researcher", "ai research", "research scientist", "ai scientist", "machine learning scientist", "computer vision engineer", "nlp engineer", "qa automation engineer", "test engineer"),
        anzsco_codes=("261399",),
        noc_codes=("21231", "21233"),
        onet_soc_codes=("15-1299.00", "15-2051.00"),
    ),
    "2521": ISCOUnitGroup(
        code="2521",
        title="Database Designers and Administrators",
        major_group_code="2",
        major_group_title="Professionals",
        sub_major_code="25",
        sub_major_title="Information and Communications Technology Professionals",
        minor_group_code="252",
        minor_group_title="Database and Network Professionals",
        keywords=("database administrator", "dba", "data engineer", "database architect", "data warehouse architect", "sql developer"),
        anzsco_codes=("262111",),
        noc_codes=("21223",),
        onet_soc_codes=("15-1242.00", "15-1243.00"),
    ),
    "2529": ISCOUnitGroup(
        code="2529",
        title="Database and Network Professionals Not Elsewhere Classified",
        major_group_code="2",
        major_group_title="Professionals",
        sub_major_code="25",
        sub_major_title="Information and Communications Technology Professionals",
        minor_group_code="252",
        minor_group_title="Database and Network Professionals",
        keywords=("cybersecurity engineer", "information security analyst", "security engineer", "penetration tester", "soc analyst", "security architect"),
        anzsco_codes=("262112",),
        noc_codes=("21220",),
        onet_soc_codes=("15-1212.00",),
    ),

    # --- Finance, Business & Administration (Sub-Major 24, 12, 13) ---
    "2411": ISCOUnitGroup(
        code="2411",
        title="Accountants",
        major_group_code="2",
        major_group_title="Professionals",
        sub_major_code="24",
        sub_major_title="Business and Administration Professionals",
        minor_group_code="241",
        minor_group_title="Finance Professionals",
        keywords=("accountant", "chartered accountant", "cpa", "auditor", "financial accountant", "tax accountant", "management accountant", "comptable"),
        anzsco_codes=("221111", "221112"),
        noc_codes=("11100",),
        onet_soc_codes=("13-2011.00",),
    ),
    "2412": ISCOUnitGroup(
        code="2412",
        title="Financial and Investment Advisers",
        major_group_code="2",
        major_group_title="Professionals",
        sub_major_code="24",
        sub_major_title="Business and Administration Professionals",
        minor_group_code="241",
        minor_group_title="Finance Professionals",
        keywords=("financial analyst", "investment banker", "portfolio manager", "investment analyst", "equity research analyst", "wealth manager"),
        anzsco_codes=("222311", "222312"),
        noc_codes=("11102", "11103"),
        onet_soc_codes=("13-2051.00", "13-2052.00"),
    ),
    "2421": ISCOUnitGroup(
        code="2421",
        title="Management and Organization Analysts",
        major_group_code="2",
        major_group_title="Professionals",
        sub_major_code="24",
        sub_major_title="Business and Administration Professionals",
        minor_group_code="242",
        minor_group_title="Administration Professionals",
        keywords=("management consultant", "business analyst", "strategy consultant", "operations analyst", "change management consultant"),
        anzsco_codes=("224711",),
        noc_codes=("11200",),
        onet_soc_codes=("13-1111.00",),
    ),
    "2422": ISCOUnitGroup(
        code="2422",
        title="Policy Administration Professionals",
        major_group_code="2",
        major_group_title="Professionals",
        sub_major_code="24",
        sub_major_title="Business and Administration Professionals",
        minor_group_code="242",
        minor_group_title="Administration Professionals",
        keywords=("policy analyst", "public policy officer", "government affairs specialist", "regulatory affairs specialist"),
        anzsco_codes=("224412",),
        noc_codes=("41400",),
        onet_soc_codes=("19-3051.00",),
    ),
    "2423": ISCOUnitGroup(
        code="2423",
        title="Personnel and Careers Professionals",
        major_group_code="2",
        major_group_title="Professionals",
        sub_major_code="24",
        sub_major_title="Business and Administration Professionals",
        minor_group_code="242",
        minor_group_title="Administration Professionals",
        keywords=("human resources specialist", "hr generalist", "recruiter", "talent acquisition specialist", "hr business partner", "hrbp"),
        anzsco_codes=("223111", "223112"),
        noc_codes=("11200",),
        onet_soc_codes=("13-1071.00",),
    ),

    # --- Hospitality & Culinary (Sub-Major 34, 51, 14) ---
    "3434": ISCOUnitGroup(
        code="3434",
        title="Chefs",
        major_group_code="3",
        major_group_title="Technicians and Associate Professionals",
        sub_major_code="34",
        sub_major_title="Legal, Social, Cultural and Related Associate Professionals",
        minor_group_code="343",
        minor_group_title="Artistic, Cultural and Culinary Associate Professionals",
        keywords=("chef", "executive chef", "head chef", "sous chef", "pastry chef", "chef de partie", "master chef", "küchenchef"),
        anzsco_codes=("351311",),
        noc_codes=("62200",),
        onet_soc_codes=("35-1011.00",),
    ),
    "1411": ISCOUnitGroup(
        code="1411",
        title="Hotel Managers",
        major_group_code="1",
        major_group_title="Managers",
        sub_major_code="14",
        sub_major_title="Hospitality, Retail and Other Services Managers",
        minor_group_code="141",
        minor_group_title="Hotel and Restaurant Managers",
        keywords=("hotel manager", "general manager hotel", "resort manager", "hospitality manager", "front office manager", "luxury hotel", "hotel general manager", "hotel director", "hotel"),
        anzsco_codes=("141111",),
        noc_codes=("60040",),
        onet_soc_codes=("11-9081.00",),
    ),
    "1412": ISCOUnitGroup(
        code="1412",
        title="Restaurant Managers",
        major_group_code="1",
        major_group_title="Managers",
        sub_major_code="14",
        sub_major_title="Hospitality, Retail and Other Services Managers",
        minor_group_code="141",
        minor_group_title="Hotel and Restaurant Managers",
        keywords=("restaurant manager", "food and beverage director", "f&b manager", "banquet manager"),
        anzsco_codes=("141111",),
        noc_codes=("60030",),
        onet_soc_codes=("11-9051.00",),
    ),

    # --- Skilled Trades & Construction (Sub-Major 71, 72, 74) ---
    "7112": ISCOUnitGroup(
        code="7112",
        title="Bricklayers and Related Workers",
        major_group_code="7",
        major_group_title="Craft and Related Trades Workers",
        sub_major_code="71",
        sub_major_title="Building and Related Trades Workers (excluding Electricians)",
        minor_group_code="711",
        minor_group_title="Building Frame and Related Trades Workers",
        keywords=("bricklayer", "mason", "stonemason", "blocklayer", "concrete finisher"),
        anzsco_codes=("331111", "331112"),
        noc_codes=("72802",),
        onet_soc_codes=("47-2021.00",),
    ),
    "7115": ISCOUnitGroup(
        code="7115",
        title="Carpenters and Joiners",
        major_group_code="7",
        major_group_title="Craft and Related Trades Workers",
        sub_major_code="71",
        sub_major_title="Building and Related Trades Workers (excluding Electricians)",
        minor_group_code="711",
        minor_group_title="Building Frame and Related Trades Workers",
        keywords=("carpenter", "joiner", "framing carpenter", "finish carpenter", "cabinetmaker"),
        anzsco_codes=("331211", "331212"),
        noc_codes=("72710",),
        onet_soc_codes=("47-2031.00",),
    ),
    "7126": ISCOUnitGroup(
        code="7126",
        title="Plumbers and Pipe Fitters",
        major_group_code="7",
        major_group_title="Craft and Related Trades Workers",
        sub_major_code="71",
        sub_major_title="Building and Related Trades Workers (excluding Electricians)",
        minor_group_code="712",
        minor_group_title="Building Finishers and Related Trades Workers",
        keywords=("plumber", "pipefitter", "gasfitter", "steamfitter", "sanitary installer"),
        anzsco_codes=("334111", "334113"),
        noc_codes=("72510",),
        onet_soc_codes=("47-2152.00",),
    ),
    "7212": ISCOUnitGroup(
        code="7212",
        title="Welders and Flamecutters",
        major_group_code="7",
        major_group_title="Craft and Related Trades Workers",
        sub_major_code="72",
        sub_major_title="Metal, Machinery and Related Trades Workers",
        minor_group_code="721",
        minor_group_title="Sheet and Structural Metal Workers, Moulders and Welders",
        keywords=("welder", "tig welder", "mig welder", "arc welder", "pipe welder", "fabricator", "flamecutter"),
        anzsco_codes=("322311",),
        noc_codes=("72106",),
        onet_soc_codes=("51-4121.00",),
    ),
    "7222": ISCOUnitGroup(
        code="7222",
        title="Toolmakers and Related Workers",
        major_group_code="7",
        major_group_title="Craft and Related Trades Workers",
        sub_major_code="72",
        sub_major_title="Metal, Machinery and Related Trades Workers",
        minor_group_code="722",
        minor_group_title="Blacksmiths, Toolmakers and Related Trades Workers",
        keywords=("machinist", "cnc machinist", "toolmaker", "die maker", "cnc operator", "lathe operator"),
        anzsco_codes=("323214", "323211"),
        noc_codes=("72100",),
        onet_soc_codes=("51-4041.00", "51-4111.00"),
    ),
    "7411": ISCOUnitGroup(
        code="7411",
        title="Building and Related Electricians",
        major_group_code="7",
        major_group_title="Craft and Related Trades Workers",
        sub_major_code="74",
        sub_major_title="Electrical and Electronic Trades Workers",
        minor_group_code="741",
        minor_group_title="Electrical Equipment Installers and Repairers",
        keywords=("electrician", "licensed electrician", "journeyman electrician", "industrial electrician", "commercial electrician", "elektriker"),
        anzsco_codes=("341111", "341112"),
        noc_codes=("72200", "72201"),
        onet_soc_codes=("47-2111.00",),
    ),

    # --- Education & Academia (Sub-Major 23) ---
    "2310": ISCOUnitGroup(
        code="2310",
        title="University and Higher Education Teachers",
        major_group_code="2",
        major_group_title="Professionals",
        sub_major_code="23",
        sub_major_title="Teaching Professionals",
        minor_group_code="231",
        minor_group_title="University and Higher Education Teachers",
        keywords=("professor", "assistant professor", "associate professor", "lecturer", "university instructor", "academic researcher", "postdoc"),
        anzsco_codes=("242111",),
        noc_codes=("41200",),
        onet_soc_codes=("25-1000.00",),
    ),
    "2330": ISCOUnitGroup(
        code="2330",
        title="Secondary Education Teachers",
        major_group_code="2",
        major_group_title="Professionals",
        sub_major_code="23",
        sub_major_title="Teaching Professionals",
        minor_group_code="233",
        minor_group_title="Secondary Education Teachers",
        keywords=("secondary school teacher", "high school teacher", "math teacher", "science teacher", "esl teacher"),
        anzsco_codes=("241411",),
        noc_codes=("41220",),
        onet_soc_codes=("25-2031.00",),
    ),

    # --- Logistics & Transport (Sub-Major 83, 13) ---
    "8332": ISCOUnitGroup(
        code="8332",
        title="Heavy Truck and Lorry Drivers",
        major_group_code="8",
        major_group_title="Plant and Machine Operators and Assemblers",
        sub_major_code="83",
        sub_major_title="Drivers and Mobile Plant Operators",
        minor_group_code="833",
        minor_group_title="Heavy Truck and Bus Drivers",
        keywords=("truck driver", "hgv driver", "heavy vehicle driver", "long haul driver", "cdl driver", "lorry driver"),
        anzsco_codes=("733111",),
        noc_codes=("73300",),
        onet_soc_codes=("53-3032.00",),
    ),
    "1324": ISCOUnitGroup(
        code="1324",
        title="Supply, Distribution and Related Managers",
        major_group_code="1",
        major_group_title="Managers",
        sub_major_code="13",
        sub_major_title="Production and Specialized Services Managers",
        minor_group_code="132",
        minor_group_title="Manufacturing, Mining, Construction and Distribution Managers",
        keywords=("logistics manager", "supply chain manager", "warehouse manager", "distribution manager", "procurement manager"),
        anzsco_codes=("133611",),
        noc_codes=("70012",),
        onet_soc_codes=("11-3071.00",),
    ),

    # --- Agriculture, Forestry and Fishery (Major Group 6) ---
    "6111": ISCOUnitGroup(
        code="6111",
        title="Field Crop and Vegetable Growers",
        major_group_code="6",
        major_group_title="Skilled Agricultural, Forestry and Fishery Workers",
        sub_major_code="61",
        sub_major_title="Market-oriented Skilled Agricultural Workers",
        minor_group_code="611",
        minor_group_title="Market Gardeners and Crop Growers",
        keywords=("agronomist", "farm manager", "crop grower", "agricultural specialist", "horticulturist", "farm supervisor"),
        anzsco_codes=("121211", "234112"),
        noc_codes=("80020", "21112"),
        onet_soc_codes=("19-1011.00", "11-9013.00"),
    ),
}


def lookup_isco_by_code(code: str) -> Optional[ISCOUnitGroup]:
    """Look up an ISCO-08 unit group by its 4-digit code."""
    return ISCO_UNIT_GROUPS.get(code.strip())


def search_isco_by_keywords(text: str) -> List[Tuple[ISCOUnitGroup, float]]:
    """
    Search ISCO unit groups matching keywords in title or job text.
    Returns list of (unit_group, match_confidence) sorted descending by specificity and relevance.
    """
    import re
    t = text.lower().strip()
    results: List[Tuple[ISCOUnitGroup, float]] = []

    for unit in ISCO_UNIT_GROUPS.values():
        best_score = 0.0
        # 1. Exact title match
        if unit.title.lower() == t:
            best_score = 1.0
        elif unit.title.lower() in t or t in unit.title.lower():
            best_score = max(best_score, 0.95)

        # 2. Keyword matches weighted by specificity and length
        for kw in unit.keywords:
            kw_clean = kw.lower()
            if re.search(r"\b" + re.escape(kw_clean) + r"\b", t):
                # Multi-word or specialized terms get top priority
                kw_len = len(kw_clean)
                word_count = len(kw_clean.split())
                if word_count > 1:
                    score = 0.92 + min(0.05, kw_len * 0.002)
                elif kw_clean in ("cardiologist", "surgeon", "radiologist", "anesthesiologist", "oncologist", "neurologist", "psychiatrist", "dermatologist"):
                    score = 0.94  # Specific medical specialties outrank generic "physician"
                else:
                    score = 0.70 + min(0.15, kw_len * 0.01)
                best_score = max(best_score, score)

        if best_score > 0.0:
            results.append((unit, best_score))

    results.sort(key=lambda x: -x[1])
    return results


def get_country_specific_occupation_code(
    isco_code: str,
    destination_country: str,
) -> Optional[Dict[str, Any]]:
    """
    Crosswalk an ISCO unit group code to the destination country's native occupation code:
      - AU / NZ -> ANZSCO
      - CA -> NOC 2021
      - US -> O*NET-SOC 2019
    """
    unit = lookup_isco_by_code(isco_code)
    if not unit:
        return None

    country = (destination_country or "").upper().strip()
    if country in ("AU", "NZ", "AUSTRALIA", "NEW ZEALAND"):
        return {
            "system": "ANZSCO",
            "codes": list(unit.anzsco_codes),
            "primary_code": unit.anzsco_codes[0] if unit.anzsco_codes else None,
        }
    elif country in ("CA", "CAN", "CANADA"):
        return {
            "system": "NOC_2021",
            "codes": list(unit.noc_codes),
            "primary_code": unit.noc_codes[0] if unit.noc_codes else None,
        }
    elif country in ("US", "USA", "UNITED STATES"):
        return {
            "system": "ONET_SOC_2019",
            "codes": list(unit.onet_soc_codes),
            "primary_code": unit.onet_soc_codes[0] if unit.onet_soc_codes else None,
        }

    return {
        "system": "ISCO_08",
        "codes": [unit.code],
        "primary_code": unit.code,
    }
