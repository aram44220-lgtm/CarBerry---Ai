"""
images.py -- Smart niche-based image resolver (zero latency, no external HTTP calls).
Strategy:
  AI outputs `image_topic` in the JSON plan.
  We match it against keyword->niche map.
  We return pre-vetted Unsplash photo IDs -> instant URL, no HTTP calls.
"""
from __future__ import annotations
import re

_NICHE_PHOTOS: dict[str, list[str]] = {
    "car_repair": [
        "1487958449943-2429e8be8625",
        "1558618666-fcd25c85cd64",
        "1601362840469-51e4a8571f28",
        "1530046339160-ce3e530c7d2f",
        "1517524285303-d6fc683dddf8",
        "1486262715619-67b85e0b08d3",
    ],
    "detailing": [
        "1607860108855-64acf2078ed9",
        "1601362840469-51e4a8571f28",
        "1510414842594-a61c69b5ae57",
        "1487958449943-2429e8be8625",
        "1558618666-fcd25c85cd64",
        "1550355291-bbee04a92027",
    ],
    "car_dealership": [
        "1549317661-d1b3e9e34bf9",
        "1580274455191-1c62773470e3",
        "1492144534655-ae79c964c9d7",
        "1503376780353-7e6692767b70",
        "1502877338535-766e1452684a",
        "1542362084-6af5a87c07d7",
    ],
    "restaurant": [
        "1414235077428-338989a2e8c0",
        "1504674900247-0877df9cc836",
        "1555396273-367ea4eb4db5",
        "1466978913421-dad2ebd01d17",
        "1543353071-087092ec393a",
        "1517248135467-4c7edcad34c4",
    ],
    "coffee": [
        "1501339847302-ac426a4a7cbb",
        "1509042239860-f550ce710b93",
        "1461023058942-a4a8bec12af9",
        "1495474472287-4d71bcdd2085",
        "1442512595331-e4f9d75f4ff7",
        "1447933601428-96c977febb6d",
    ],
    "pizza": [
        "1565299624946-b28f40a0ae38",
        "1534308983496-4fabb1a015ee",
        "1513104890138-7c749659a591",
        "1571407970349-bc81e71e4580",
        "1555072956-7758afb20e8f",
        "1604382355076-af4b0eb60143",
    ],
    "sushi": [
        "1553621042-f6e147245754",
        "1582450871851-a5539884b587",
        "1618671881452-bf7bf4a6df57",
        "1617196034183-421b4040d20d",
        "1562802378-063ec186a863",
        "1563612116625-3012372fccce",
    ],
    "bakery": [
        "1555507036-ab1f4038808a",
        "1509440159596-0249088772ff",
        "1486427944299-d1955d23e34d",
        "1568702846914-96b305d2aaeb",
        "1530610476181-d83430b064d9",
        "1616684000067-36952fde56ec",
    ],
    "bar": [
        "1514362545857-3bc16c4c7d1b",
        "1470337458703-4ad1d7ba7cdd",
        "1516997121675-4c2d1684aa3e",
        "1560512823-829485b8bf24",
        "1559628233-100c798642d4",
        "1506368540-a09dd2b2a930",
    ],
    "barbershop": [
        "1585747860715-2ba37e788b70",
        "1503951914875-452162b0f3f1",
        "1621605815971-fbc98d665033",
        "1534297635766-a262cdcb8ee4",
        "1559599101-f09722fb4948",
        "1582095133179-bfd08e2585c3",
    ],
    "beauty_salon": [
        "1522337360788-8b13dee7a37e",
        "1487412947147-5cebf100d293",
        "1562322140-8baeececf3df",
        "1596462502278-27bfdc403869",
        "1620756235986-bc571f42a4b3",
        "1633681926022-84c23e8cb2d6",
    ],
    "spa": [
        "1540555700478-4be289fbecef",
        "1599901854208-d1c4ae3e5ce7",
        "1571019613454-1cb2f99b2d8b",
        "1573461160327-ce9b81df3f27",
        "1583416750470-965b2707b531",
        "1507003211169-0a1dd7228f2d",
    ],
    "tattoo": [
        "1558618047-3c0657b6e7b4",
        "1509460913899-515f1df34fea",
        "1598965402089-897ce52e8355",
        "1475695752828-d96b1b5a90c5",
        "1562155618-e1a8bc2eb3f6",
        "1603573336165-09ff3c0e64a3",
    ],
    "dentist": [
        "1606811841689-23dfddce3e52",
        "1609840114035-3c981b0f2672",
        "1588776814546-daab30f310ce",
        "1598256989791-1b6e9fd1abb2",
        "1576091160550-2173dba999ef",
        "1559757175-0eb30cd8c063",
    ],
    "medical": [
        "1576671081837-49000212a370",
        "1504813184591-a4a78bc523c1",
        "1530497610245-f1fe21f2b8ae",
        "1538108149393-fbbd82ef8fd9",
        "1559757148-5c350d0d3c56",
        "1582719508461-905c673771fd",
    ],
    "fitness": [
        "1534438327276-14e5300c3a48",
        "1571902943202-507ec2618e8f",
        "1583454110551-21f2fa2afe61",
        "1549060279-7e168fcee0c2",
        "1517963628622-1427a8e04e58",
        "1574680096145-d05b474e2155",
    ],
    "yoga": [
        "1544367567-0f2fcb009e0b",
        "1506126613408-eca07ce68773",
        "1588286840104-8957b019727f",
        "1571019613454-1cb2f99b2d8b",
        "1599447292325-a46af85a0e26",
        "1575052814086-f385e2e2ad1b",
    ],
    "construction": [
        "1503387762-592deb58ef4e",
        "1504307651254-35680f356dfd",
        "1590069261209-f8b9992ab9de",
        "1513694203232-719a6b918f1b",
        "1488459716781-31db52582fe9",
        "1497366412874-3415097a27fe",
    ],
    "cleaning": [
        "1581578731548-c64695cc6952",
        "1563453392212-326f5e854473",
        "1527515637462-cff94eecc1ac",
        "1584820927498-cad076eae09c",
        "1556909114-f6e7ad7d3136",
        "1521791055366-0d553872b420",
    ],
    "flowers": [
        "1490750967868-88df5691cc4e",
        "1549465220-1a629f337fe8",
        "1457089328109-3d3f7777f6ff",
        "1524661135-e4711e000c79",
        "1487530811176-3780de880c2d",
        "1582794543139-74e37a63c5b0",
    ],
    "legal": [
        "1589829545105-f51cca8c5955",
        "1453945619913-79ec89a82c51",
        "1521791055366-0d553872b420",
        "1497366412874-3415097a27fe",
        "1486406928808-e8c49bc72d5e",
        "1507003211169-0a1dd7228f2d",
    ],
    "real_estate": [
        "1560518883-ce09059eeffa",
        "1512917774080-9991f1c4c750",
        "1570129477492-45c003edd2be",
        "1558036117-15d82a90b9b1",
        "1497366216548-37526070297c",
        "1493809842364-78817add7ffb",
    ],
    "pets": [
        "1450778869180-41d0601e046e",
        "1587300003388-59208cc962cb",
        "1548199973-03cce0bbc87b",
        "1560743641-3914f2c45db1",
        "1601758174119-87ef09b72f0f",
        "1537151625747-0369537e09fe",
    ],
    "wedding": [
        "1519741497674-4be6b3b09f3a",
        "1522673607200-164d1b6ce486",
        "1606800052052-61bf7eb1452d",
        "1465495976277-a40f05c89e00",
        "1478145787956-acef1659b36b",
        "1583939003579-730e3918a45a",
    ],
    "agency": [
        "1497366811353-6870744d04b2",
        "1541746972996-4e0b0f43e02a",
        "1564069114553-7215e1ff1890",
        "1556742049-0cfed4f6a45d",
        "1497366754035-f200968a6e72",
        "1522202176988-66273c2fd55f",
    ],
    "portfolio": [
        "1524758631624-e2822e304c36",
        "1497366754035-f200968a6e72",
        "1467232004584-a241de8bcf5d",
        "1484417894907-623942c8ee29",
        "1586717799252-bd134ad00e26",
        "1558618666-fcd25c85cd64",
    ],
    "photography": [
        "1452587925148-ce544e77e70d",
        "1516035069371-29a1b244cc32",
        "1542038784456-1ea8e935640e",
        "1500051638674-ff996a0ec29e",
        "1471341971476-ae15ff5dd4ea",
        "1519638831568-d9897f54ed69",
    ],
    "saas": [
        "1551288049-bebda4e38f71",
        "1460925895917-afdab827c52f",
        "1504868584819-f8e8b4b6d7e3",
        "1498050108023-c5249f4df085",
        "1618401471353-b98afee0b2eb",
        "1555066931-4365d14ad3cd",
    ],
    "startup": [
        "1553877522-43269d4ea984",
        "1522202176988-66273c2fd55f",
        "1497366216548-37526070297c",
        "1528747045269-390fe33c19f2",
        "1461749280684-dccba630e2f6",
        "1531482615713-2afd69097998",
    ],
    "crypto": [
        "1518546305927-b44af8af93d7",
        "1611974789855-9c2a0a7236a3",
        "1504711434969-e33886168f5c",
        "1526304640581-d334cdbbf45e",
        "1535320903710-a36a5caba4b3",
        "1639762681485-074b7f938ba0",
    ],
    "clothing": [
        "1441986300917-64674bd600d8",
        "1490481651871-ab68de25d43d",
        "1523275335684-37898b6baf30",
        "1542291026-7eec264c27ff",
        "1515886657613-9f3515b0c78f",
        "1469334031218-e382a71b716b",
    ],
    "jewelry": [
        "1515562141207-7a88fb7ce338",
        "1573408301185-9521e7d27c82",
        "1611591437281-460bfbe1220a",
        "1601121141461-9d6647bef0a1",
        "1585386959984-a4155224a1ad",
        "1531995642153-e8e3b8b6d1ca",
    ],
    "hotel": [
        "1551882547-ff40c4a49d5f",
        "1566073771259-470fdf0ce4f7",
        "1445019980597-93fa8acb246c",
        "1520250497591-112f2f40a3f4",
        "1584132967334-10e028bd69f7",
        "1571003123894-1eda6e37ee72",
    ],
    "ecommerce": [
        "1441986300917-64674bd600d8",
        "1490481651871-ab68de25d43d",
        "1523275335684-37898b6baf30",
        "1542291026-7eec264c27ff",
        "1556742049-0cfed4f6a45d",
        "1416949929422-a1d9c8ac056e",
    ],
    "education": [
        "1522202176988-66273c2fd55f",
        "1509062522246-3755977927d5",
        "1497633762265-9d179a990aa6",
        "1503676260728-1c00da094a0b",
        "1456513080510-7bf3a84b82f8",
        "1434030216411-0b793f4b4173",
    ],
    "personal": [
        "1500648767791-00dcc994a43e",
        "1507003211169-0a1dd7228f2d",
        "1522071820093-c0548b5bc74e",
        "1484417894907-623942c8ee29",
        "1499557354967-2b2d8910638e",
        "1523240795612-9a054b0db644",
    ],
    "generic": [
        "1497366811353-6870744d04b2",
        "1541746972996-4e0b0f43e02a",
        "1524758631624-e2822e304c36",
        "1556742049-0cfed4f6a45d",
        "1522202176988-66273c2fd55f",
        "1503376780353-7e6692767b70",
    ],
}

_KEYWORD_MAP: list[tuple[str, str]] = [
    ("авто", "car_repair"), ("машин", "car_repair"), ("автосерв", "car_repair"),
    ("шиномонтаж", "car_repair"), ("мотоц", "car_repair"),
    ("car repair", "car_repair"), ("auto repair", "car_repair"), ("mechanic", "car_repair"),
    ("garage", "car_repair"), ("automotive", "car_repair"), ("tire", "car_repair"),
    ("детейлинг", "detailing"), ("detailing", "detailing"), ("автомойк", "detailing"),
    ("car wash", "detailing"), ("valeting", "detailing"),
    ("автосалон", "car_dealership"), ("car dealer", "car_dealership"),
    ("ресторан", "restaurant"), ("restaurant", "restaurant"), ("dining", "restaurant"),
    ("бистро", "restaurant"), ("bistro", "restaurant"),
    ("кофе", "coffee"), ("кафе", "coffee"), ("coffee", "coffee"), ("cafe", "coffee"),
    ("espresso", "coffee"),
    ("пицц", "pizza"), ("pizza", "pizza"), ("pizzeria", "pizza"),
    ("суши", "sushi"), ("sushi", "sushi"), ("японс", "sushi"),
    ("рамен", "sushi"), ("ramen", "sushi"), ("азиатс", "sushi"),
    ("пекарн", "bakery"), ("bakery", "bakery"), ("кондитер", "bakery"),
    ("торт", "bakery"), ("cake", "bakery"), ("хлеб", "bakery"), ("pastry", "bakery"),
    ("коктейл", "bar"), ("cocktail", "bar"), ("lounge", "bar"),
    ("барбершоп", "barbershop"), ("barbershop", "barbershop"), ("барбер", "barbershop"),
    ("стрижк", "barbershop"), ("barber", "barbershop"),
    ("парикмахер", "beauty_salon"), ("hair salon", "beauty_salon"),
    ("маникюр", "beauty_salon"), ("nail", "beauty_salon"), ("makeup", "beauty_salon"),
    ("спа", "spa"), ("spa", "spa"), ("массаж", "spa"), ("massage", "spa"),
    ("wellness", "spa"), ("релакс", "spa"),
    ("тату", "tattoo"), ("tattoo", "tattoo"),
    ("стоматол", "dentist"), ("зубн", "dentist"), ("dentist", "dentist"), ("dental", "dentist"),
    ("клиник", "medical"), ("медиц", "medical"), ("clinic", "medical"),
    ("врач", "medical"), ("doctor", "medical"), ("hospital", "medical"),
    ("фитнес", "fitness"), ("тренажер", "fitness"), ("gym", "fitness"),
    ("спортзал", "fitness"),
    ("йога", "yoga"), ("yoga", "yoga"), ("пилатес", "yoga"), ("pilates", "yoga"),
    ("ремонт квартир", "construction"), ("стройк", "construction"), ("renovation", "construction"),
    ("construction", "construction"), ("архитект", "construction"),
    ("клининг", "cleaning"), ("cleaning", "cleaning"), ("уборк", "cleaning"),
    ("цвет", "flowers"), ("flower", "flowers"), ("флорист", "flowers"), ("букет", "flowers"),
    ("свадьб", "wedding"), ("wedding", "wedding"), ("невест", "wedding"),
    ("юрист", "legal"), ("адвокат", "legal"), ("legal", "legal"), ("law firm", "legal"),
    ("недвижим", "real_estate"), ("real estate", "real_estate"),
    ("питомц", "pets"), ("ветеринар", "pets"), ("veterinar", "pets"), ("pet shop", "pets"),
    ("агентств", "agency"), ("agency", "agency"), ("маркетинг", "agency"),
    ("брендинг", "agency"), ("реклам", "agency"),
    ("фотограф", "photography"), ("photog", "photography"), ("photo studio", "photography"),
    ("saas", "saas"), ("software", "saas"), ("platform", "saas"),
    ("стартап", "startup"), ("startup", "startup"),
    ("крипт", "crypto"), ("bitcoin", "crypto"), ("blockchain", "crypto"),
    ("портфолио", "portfolio"), ("portfolio", "portfolio"), ("freelanc", "portfolio"),
    ("одежд", "clothing"), ("fashion", "clothing"), ("бутик", "clothing"),
    ("ювелир", "jewelry"), ("jewelry", "jewelry"), ("часы", "jewelry"),
    ("магазин", "ecommerce"), ("интернет-маг", "ecommerce"), ("ecommerce", "ecommerce"),
    ("отель", "hotel"), ("hotel", "hotel"), ("хостел", "hotel"),
    ("обучен", "education"), ("курс", "education"), ("school", "education"),
    ("education", "education"), ("academy", "education"),
]


def _build_url(photo_id: str, w: int = 1600, q: int = 85) -> str:
    return f"https://images.unsplash.com/photo-{photo_id}?auto=format&fit=crop&w={w}&q={q}"


def resolve_niche(
    image_topic: str = "",
    site_type: str = "",
    brand: str = "",
    title: str = "",
) -> str:
    """Return best niche key given any combination of context."""
    haystack = " ".join([
        image_topic or "", site_type or "", brand or "", title or ""
    ]).lower()
    for keyword, niche in _KEYWORD_MAP:
        if keyword.lower() in haystack:
            return niche
    if site_type in _NICHE_PHOTOS:
        return site_type
    return "generic"


def get_images(
    image_topic: str = "",
    site_type: str = "",
    brand: str = "",
    title: str = "",
    count: int = 4,
) -> list[str]:
    """Return `count` topic-matched image URLs (instant, no HTTP calls)."""
    niche = resolve_niche(image_topic, site_type, brand, title)
    ids = _NICHE_PHOTOS.get(niche, _NICHE_PHOTOS["generic"])
    widths = [1600, 1200, 1200, 1000, 900, 900]
    result: list[str] = []
    for i in range(count):
        idx = i % len(ids)
        w = widths[i] if i < len(widths) else 900
        result.append(_build_url(ids[idx], w=w))
    return result
