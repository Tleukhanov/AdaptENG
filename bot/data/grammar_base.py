"""База знаний грамматики для RAG (русскоязычные чанки).

Каждый чанк — одна мысль (правило + формула + 1 классический пример).
Классические примеры — запасные: если интересы ученика неизвестны,
LLM берёт пример отсюда. Если интересы известны — строит свой.
"""

GRAMMAR_CHUNKS = [
    {
        "id": "present_simple",
        "title": "Present Simple",
        "text": (
            "Present Simple — регулярные действия и факты. Формула: подлежащее + глагол. "
            "Для he/she/it к глаголу добавляется -s/-es. "
            "Классический пример: He runs every morning."
        ),
    },
    {
        "id": "present_continuous",
        "title": "Present Continuous",
        "text": (
            "Present Continuous — действие прямо сейчас. Формула: am/is/are + глагол-ing. "
            "Классический пример: I am reading now."
        ),
    },
    {
        "id": "present_perfect",
        "title": "Present Perfect",
        "text": (
            "Present Perfect — прошлое с результатом в настоящем. Формула: have/has + V3 "
            "(третья форма глагола). Маркеры: just, already, ever, never, yet. "
            "Классический пример: I have just eaten."
        ),
    },
    {
        "id": "present_perfect_vs_past_simple",
        "title": "Present Perfect vs Past Simple",
        "text": (
            "Present Perfect — важен результат (I have lost my keys — ключей нет сейчас). "
            "Past Simple — важен факт в прошлом с указанием времени (I lost my keys yesterday). "
            "Если есть yesterday/last year — только Past Simple. "
            "Классический пример: I have seen this movie vs I saw this movie yesterday."
        ),
    },
    {
        "id": "past_simple",
        "title": "Past Simple",
        "text": (
            "Past Simple — завершённое действие в прошлом. Правильные глаголы + -ed, "
            "неправильные — вторая форма (went, ate, saw). "
            "Классический пример: We visited Astana last year."
        ),
    },
    {
        "id": "past_continuous",
        "title": "Past Continuous",
        "text": (
            "Past Continuous — длительное действие в момент прошлого. Формула: was/were + глагол-ing. "
            "Часто пара с Past Simple: длинное прерывалось коротким. "
            "Классический пример: I was sleeping when you called."
        ),
    },
    {
        "id": "past_perfect",
        "title": "Past Perfect",
        "text": (
            "Past Perfect — «прошлое в прошлом»: действие завершилось раньше другого прошлого. "
            "Формула: had + V3. "
            "Классический пример: When I arrived, the train had left."
        ),
    },
    {
        "id": "future_simple",
        "title": "Future Simple (will)",
        "text": (
            "Will — спонтанные решения, обещания, прогнозы. Формула: will + глагол. "
            "Классический пример: I will help you."
        ),
    },
    {
        "id": "be_going_to",
        "title": "Be going to",
        "text": (
            "Be going to — планы и намерения. Формула: am/is/are + going to + глагол. "
            "Отличие от will: going to — заранее решено, will — решил сейчас. "
            "Классический пример: I am going to learn English."
        ),
    },
    {
        "id": "articles",
        "title": "Артикли a/an/the",
        "text": (
            "A/an — первое упоминание исчисляемого в единственном числе. "
            "The — уже известное, конкретное. Во множественном и с неисчисляемыми a/an нет. "
            "Классический пример: A cat sat on the mat."
        ),
    },
    {
        "id": "conditionals_01",
        "title": "Conditionals 0 и 1",
        "text": (
            "Zero Conditional — общие истины: If + Present Simple, Present Simple. "
            "First Conditional — реальное будущее: If + Present Simple, will + глагол. "
            "Классический пример: If it rains, we will stay at home."
        ),
    },
    {
        "id": "conditionals_23",
        "title": "Conditionals 2 и 3",
        "text": (
            "Second Conditional — нереальное настоящее: If + Past Simple, would + глагол. "
            "Third Conditional — сожаление о прошлом: If + Past Perfect, would have + V3. "
            "Классический пример: If I had studied, I would have passed."
        ),
    },
    {
        "id": "passive",
        "title": "Passive Voice",
        "text": (
            "Passive — важно действие/объект, а не кто делает. Формула: be + V3, время меняется глаголом be. "
            "Классический пример: The cake was eaten."
        ),
    },
    {
        "id": "reported_speech",
        "title": "Reported Speech",
        "text": (
            "Косвенная речь: сдвиг времени назад (Present Simple → Past Simple, will → would). "
            "Say + that необязательно. Вопросы перестраиваются в утверждения. "
            "Классический пример: He said (that) he was tired."
        ),
    },
    {
        "id": "modals",
        "title": "Модальные глаголы",
        "text": (
            "Can — умение, must — долг/приказ, should — совет, may/might — возможность. "
            "После модальных — глагол без to и без -s. "
            "Классический пример: You should rest."
        ),
    },
    {
        "id": "gerund_infinitive",
        "title": "Gerund vs Infinitive",
        "text": (
            "После enjoy, finish, mind — только герундий (verb-ing). "
            "После want, decide, plan — только инфинитив (to + verb). "
            "Некоторые глаголы меняют смысл: stop smoking (бросить) vs stop to smoke (остановиться чтобы). "
            "Классический пример: I enjoy reading."
        ),
    },
    {
        "id": "much_many",
        "title": "Much / Many / A lot",
        "text": (
            "Much — неисчисляемые (much water), many — исчисляемые во множественном (many books). "
            "A lot of — универсально для обоих. В вопросах и отрицаниях much/many, в утвердительных — a lot of. "
            "Классический пример: How much time? How many people?"
        ),
    },
    {
        "id": "comparatives",
        "title": "Сравнения",
        "text": (
            "Короткие прилагательные: -er + than (taller than). Длинные: more + прилагательное (more beautiful than). "
            "Superlative: the + -est / the most. Исключения: good-better-best, bad-worse-worst. "
            "Классический пример: This book is more interesting than that one."
        ),
    },
    {
        "id": "prepositions_place",
        "title": "Предлоги места in/at/on",
        "text": (
            "In — внутри/город/страна (in the box, in Astana). At — точка (at the bus stop, at 5 pm — и время). "
            "On — поверхность/день (on the table, on Monday). "
            "Классический пример: The keys are on the table."
        ),
    },
    {
        "id": "there_is_are",
        "title": "There is / There are",
        "text": (
            "There is — единственное число, there are — множественное. Описывает наличие, не действие. "
            "Классический пример: There is a book on the desk."
        ),
    },
    {
        "id": "questions",
        "title": "Построение вопросов",
        "text": (
            "Общий вопрос: вспомогательный глагол + подлежащее + глагол (Do you like tea?). "
            "Специальный: wh-слово + вспомогательный + подлежащее + глагол (Where do you live?). "
            "С глаголом to be вспомогательный не нужен (Are you ready?). "
            "Классический пример: What time do you wake up?"
        ),
    },
    {
        "id": "negation",
        "title": "Отрицания",
        "text": (
            "Отрицание строится через do/does/did + not + глагол без изменений. "
            "С to be: просто not после (is not). Двойных отрицаний в английском нет. "
            "Классический пример: I do not know."
        ),
    },
    {
        "id": "used_to",
        "title": "Used to",
        "text": (
            "Used to + глагол — привычка в прошлом, которой больше нет. "
            "Не путать с be used to + gerund (привык к чему-то сейчас). "
            "Классический пример: I used to play football."
        ),
    },
    {
        "id": "plurals",
        "title": "Множественное число",
        "text": (
            "Обычно + -s/-es. Исключения надо учить: man-men, child-children, foot-feet, "
            "mouse-mice, sheep-sheep, fish-fish. "
            "Классический пример: One child, two children."
        ),
    },
    {
        "id": "to_be",
        "title": "Глагол to be",
        "text": (
            "To be (am/is/are) нужен, когда нет действия: состояния, профессии, места. "
            "Я — I am, он/она/оно — is, мы/вы/они — are. "
            "Классический пример: She is a teacher. They are home."
        ),
    },
    {
        "id": "present_perfect_continuous",
        "title": "Present Perfect Continuous",
        "text": (
            "Present Perfect Continuous — действие длилось до настоящего момента и важны "
            "длительность/результат. Формула: have/has been + глагол-ing. "
            "Классический пример: I have been learning English for two years."
        ),
    },
    {
        "id": "past_perfect_continuous",
        "title": "Past Perfect Continuous",
        "text": (
            "Past Perfect Continuous — длительное действие, которое шло до другого момента "
            "в прошлом. Формула: had been + глагол-ing. "
            "Классический пример: I had been waiting for an hour when she arrived."
        ),
    },
    {
        "id": "future_continuous",
        "title": "Future Continuous",
        "text": (
            "Future Continuous — действие будет происходить в конкретный момент в будущем. "
            "Формула: will be + глагол-ing. "
            "Классический пример: This time tomorrow I will be flying to London."
        ),
    },
    {
        "id": "future_perfect",
        "title": "Future Perfect",
        "text": (
            "Future Perfect — действие завершится к определённому моменту в будущем. "
            "Формула: will have + V3. "
            "Классический пример: By June I will have finished the course."
        ),
    },
    {
        "id": "imperative",
        "title": "Повелительное наклонение",
        "text": (
            "Просьба/приказ = глагол в первой форме без подлежащего (в ед. и мн. числе). "
            "Отрицание — don't + глагол. "
            "Классический пример: Open the door. Don't be late."
        ),
    },
    {
        "id": "stative_verbs",
        "title": "Глаголы состояния",
        "text": (
            "Stative-глаголы (know, like, want, need, understand, believe, love) не ставятся "
            "в Continuous: I know, а не I am knowing. "
            "Классический пример: I like this song."
        ),
    },
    {
        "id": "adverbs_of_frequency",
        "title": "Наречия частотности",
        "text": (
            "Always, usually, often, sometimes, never стоят перед смысловым глаголом, "
            "но после to be. Вопрос: How often...? "
            "Классический пример: I always drink coffee in the morning. She is never late."
        ),
    },
    {
        "id": "some_any",
        "title": "Some / Any / No",
        "text": (
            "Some — утвердительные и предложения-просьбы/предложения. Any — вопросы и "
            "отрицания. No — отрицание без not (совсем нет). "
            "Классический пример: I have some time. Do you have any questions? I have no idea."
        ),
    },
    {
        "id": "each_every",
        "title": "Each / Every",
        "text": (
            "Both = каждый отдельно, every = каждый из группы/все вместе. Оба требуют "
            "глагола в единственном числе. "
            "Классический пример: Each student gets a book. Every day is different."
        ),
    },
    {
        "id": "both_either_neither",
        "title": "Both / Either / Neither",
        "text": (
            "Both — оба (мн. число), either — любой из двух, neither — ни один из двух "
            "(утвердительный глагол в ед. числе). "
            "Классический пример: Both answers are correct. Neither answer is right."
        ),
    },
    {
        "id": "too_enough",
        "title": "Too / Enough",
        "text": (
            "Too + прилагательное — слишком (негатив). Прилагательное + enough — достаточно; "
            "enough + существительное. "
            "Классический пример: This tea is too hot. It's warm enough. We have enough time."
        ),
    },
    {
        "id": "so_such",
        "title": "So / Such",
        "text": (
            "So + прилагательное/наречие (so fast). Such + (a/an) + прилагательное + "
            "существительное (such a nice day). "
            "Классический пример: The film was so boring. It was such a boring film."
        ),
    },
    {
        "id": "question_tags",
        "title": "Question tags",
        "text": (
            "Короткий «хвостик» в конце предложения: да → не да, отрицание → да. "
            "После I am — aren't I. "
            "Классический пример: You are tired, aren't you? She doesn't drive, does she?"
        ),
    },
    {
        "id": "relative_clauses",
        "title": "Относительные придаточные",
        "text": (
            "Who — люди, which — вещи, that — люди и вещи (в определительных), whose — "
            "принадлежность. Порядок: существительное + who/which/that + остальное. "
            "Классический пример: The man who lives next door is a chef."
        ),
    },
    {
        "id": "defining_non_defining",
        "title": "Defining vs non-defining",
        "text": (
            "Defining-придаточное (без запятых) уточняет, о ком/чем речь. Non-defining "
            "(с запятыми) добавляет доп. информацию; его нельзя опускать без потери смысла. "
            "Классический пример: The book that I lost was expensive. My brother, who lives in Astana, is here."
        ),
    },
    {
        "id": "wish",
        "title": "I wish / If only",
        "text": (
            "Сожаление о настоящем: I wish + Past Simple (I wish I knew it). О прошлом: "
            "I wish + Past Perfect (I wish I had studied). Об изменениях: I wish you would stop."
        ),
    },
    {
        "id": "modal_perfect",
        "title": "Модальные + have + V3",
        "text": (
            "Догадки и сожаления о прошлом: must have + V3 (точно было), may/might have + V3 "
            "(возможно), should have + V3 (надо было), couldn't have + V3 (вряд ли). "
            "Классический пример: You should have called me."
        ),
    },
    {
        "id": "have_to_must",
        "title": "Have to / Must",
        "text": (
            "Must — внутренний долг/сильное правило. Have to — внешняя необходимость. "
            "Отрицание разное: must not = запрещено, don't have to = не обязательно. "
            "Классический пример: I have to work tomorrow. You must not smoke here."
        ),
    },
    {
        "id": "polite_requests",
        "title": "Вежливые просьбы",
        "text": (
            "Could you...? Can you...? Would you mind + ing? — вежливые просьбы. "
            "После Would you mind — герундий. "
            "Классический пример: Could you help me, please? Would you mind opening the window?"
        ),
    },
    {
        "id": "prepositions_time",
        "title": "Предлоги времени",
        "text": (
            "At — точное время и праздники (at 5 pm, at Christmas). On — дни и даты "
            "(on Monday, on 5 May). In — месяцы, годы, части дня (in July, in 2024, in the morning). "
            "Классический пример: I start work at 9 on Monday."
        ),
    },
    {
        "id": "phrasal_verbs",
        "title": "Фразовые глаголы",
        "text": (
            "Глагол + частица (up/down/off/on...) меняет смысл: give up = бросить, look after = "
            "заботиться. С местоимением частица ставится после (pick it up), с существительным — "
            "можно и так, и так. "
            "Классический пример: Please turn off the TV. Please turn it off."
        ),
    },
    {
        "id": "make_let_allow",
        "title": "Make / Let / Allow",
        "text": (
            "Make someone do — заставить. Let someone do — позволить без to. Allow someone to do — "
            "разрешать (с to). "
            "Классический пример: My parents make me study. Let me help you. They allowed us to stay."
        ),
    },
    {
        "id": "able_to",
        "title": "Be able to / Had to",
        "text": (
            "Can не имеет форм прошлого/будущего: was/were able to = смог (в прошлом), will be able to = "
            "сможет. Место must в прошлом — had to. "
            "Классический пример: I was able to finish the report. I had to wait."
        ),
    },
    {
        "id": "would_like",
        "title": "Would like",
        "text": (
            "Would like = хочу (вежливо), + to + глагол или + существительное. Вопросы: "
            "Would you like some tea? Would you like to join us? "
            "Классический пример: I would like a coffee, please."
        ),
    },
    {
        "id": "for_since",
        "title": "For / Since",
        "text": (
            "С Present Perfect: for + период (for two years), since + момент старта "
            "(since 2020). Ключевой вопрос: How long have you...? "
            "Классический пример: I have lived here since 2019. I have known him for 5 years."
        ),
    },
    {
        "id": "zero_article",
        "title": "Нулевой артикль",
        "text": (
            "Артикль не ставится: с именами, странами (кроме the USA, the UK), языками, "
            "ежедневной едой и абстрактными понятиями в общем смысле. "
            "Классический пример: I love music. She speaks English."
        ),
    },
    {
        "id": "linking_words",
        "title": "Связки also/however/so",
        "text": (
            "Also — тоже (в середине), too — тоже (в конце), however — однако, but — но, "
            "so — поэтому, therefore — следовательно, because — потому что. "
            "Классический пример: It was late, however, we continued. I was tired, so I slept."
        ),
    },
    {
        "id": "possessives",
        "title": "Притяжательные my/mine",
        "text": (
            "Перед существительным: my, your, his, her, its, our, their. Без существительного: "
            "mine, yours, his, hers, ours, theirs. Принадлежность людей — 's: John's car. "
            "Классический пример: This is my bag. This bag is mine. It is John's idea."
        ),
    },
    {
        "id": "countable_uncountable",
        "title": "Исчисляемые и неисчисляемые",
        "text": (
            "Исчисляемые — можно посчитать (one apple, two apples), неисчисляемые — нет "
            "(water, money, information). Неисчисляемые: нет a/an и множественного числа, "
            "только some/much/a little. "
            "Классический пример: I need some water. He gave me useful advice."
        ),
    },
]
