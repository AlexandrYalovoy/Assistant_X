# Assistant X — Copyright (C) 2026 Alexandr Yalovoy
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Files of administrative pages only stay out of the library (intake/admin_filter.py, the author 2026-11-03): a title
page with an approval sheet, an implementation plan, a cover letter alone are set aside; the same pages bound with a
real document, a catalog, a notice of change, an order that approves rules, the explanatory note of a design and an
unreadable scan go in; the minutes of a meeting alone are a doubt, taken in with a warning."""

import csv

from assistant_x.intake import admin_filter as A
from assistant_x.intake.state import State


def text(*pages):
    return "".join(f"=== page {i} ===\n\n{p}\n\n" for i, p in enumerate(pages, 1))


TITLE = (
    "УТВЕРЖДАЮ Генеральный директор ООО «Нефтесервис» _________ И.И. Иванов «__» ________ 2024 г. Методический документ "
    "Требования к составу и содержанию основных технических решений версия 1.0 г. Санкт-Петербург"
)
APPROVAL = (
    "ЛИСТ СОГЛАСОВАНИЯ Начальник управления _______ Петров П.П. Главный инженер _______ Сидоров С.С. дата подпись " * 2
)
PLAN_1 = (
    "План мероприятий по внедрению методического документа М-01.02.03-04 «Требования к подготовке нефти» версия 1.0 "
    "Наименование мероприятия Организация-исполнитель Ответственный Сроки Контроль исполнения 1. Утвердить НМД в ДО "
    "Генеральный директор ДО 2 недели с момента уведомления Руководитель направления. "
)
PLAN_2 = (
    "2. Ознакомить сотрудников структурных подразделений с требованиями документа в рамках коммуникационных сессий "
    "Руководители подразделений в течение месяца с даты утверждения Владелец процесса. 3. Отчитаться об исполнении "
    "мероприятий плана перед владельцем процесса Подразделение стандартизации ежеквартально Руководитель направления. "
)
STANDARD = (
    "1 Область применения Настоящий стандарт распространяется на сепараторы нефтегазовые. 2 Нормативные ссылки "
    "ГОСТ 34347. 5 Технические требования 5.1 Рабочее давление сепаратора не более 6,3 МПа, температура от минус 40 "
    "до 100 °С. 5.2 Толщина стенки корпуса сосуда из стали 09Г2С не менее 12 мм, диаметр штуцера 150 мм. "
) * 3


def test_title_and_approval_only_rejected():
    v = A.classify("Титул и лист согласования.pdf", text(TITLE, APPROVAL))
    assert v["verdict"] == "reject" and v["kinds"] == ["title_page", "approval_sheet"]


def test_plan_only_part_rejected_over_its_pages():
    v = A.classify("План мероприятий.docx", text(TITLE, PLAN_1, PLAN_2))
    assert v["verdict"] == "reject" and "implementation_plan" in v["kinds"]
    # "введение в действие" on a later page of the plan is no clause "Введение" of real content
    later = PLAN_2 + " 4. Обеспечить введение в действие документа в дочерних обществах с даты приказа. "
    assert A.classify("9.pdf", text(PLAN_1, later))["verdict"] == "reject"


def test_title_approval_and_a_real_standard_accepted():
    assert A.classify("ГОСТ 1234-2020.pdf", text(TITLE, APPROVAL, STANDARD, STANDARD))["verdict"] is None


def test_catalog_accepted():
    v = A.classify("Каталог продукции 2024.pdf", text(TITLE, "Каталог продукции. " + PLAN_2))
    assert v["verdict"] is None and v["rule"] == "keep:catalog"


def test_change_notice_and_rules_order_accepted():
    notice = "ИЗВЕЩЕНИЕ ОБ ИЗМЕНЕНИИ № 3 к ГОСТ 1234-2020. Пункт 5.1 изложить в новой редакции. " + PLAN_2
    assert A.classify("Изм. 3.pdf", text(notice))["verdict"] is None
    order = "ПРИКАЗ Об утверждении Правил технической эксплуатации электроустановок потребителей. " + PLAN_2
    assert A.classify("Приказ.pdf", text(order, STANDARD))["verdict"] is None


def test_design_explanatory_note_is_no_note_to_a_draft_norm():
    design = "ПОЯСНИТЕЛЬНАЯ ЗАПИСКА Раздел 5. Сведения об инженерном оборудовании. Куст скважин № 12. " + PLAN_2
    assert A.classify("ПЗ раздела 5.pdf", text(design))["verdict"] is None
    draft = "ПОЯСНИТЕЛЬНАЯ ЗАПИСКА к проекту НМД 24015 по бизнес-процессу 19.04.01. Проект разработан вследствие " + PLAN_2
    assert A.classify("ПЗ.docx", text(draft))["verdict"] == "reject"


def test_cover_letter_alone_rejected_its_attachment_judged_by_itself():
    letter = "Сопроводительное письмо. Уважаемый Иван Иванович! Направляем Вам технические условия на трубы. " * 2
    assert A.classify("Письмо.pdf", text(letter))["verdict"] == "reject"
    assert A.classify("ТУ на трубы.pdf", text(STANDARD))["verdict"] is None


def test_unreadable_scan_never_rejected_on_a_guess():
    assert A.classify("Скан титула.pdf", text("УТВЕРЖДАЮ", "", ""))["verdict"] is None


def test_minutes_of_a_meeting_alone_are_a_doubt():
    minutes = "ПРОТОКОЛ совещания по вопросам проектирования объекта. Присутствовали: Иванов, Петров. РЕШИЛИ: " + PLAN_2
    assert A.classify("Протокол.pdf", text(minutes))["verdict"] == "warn"


class Cfg(dict):
    def __init__(self, root, **kw):
        super().__init__(**{"admin_filter": True, "admin_accept": [], **kw})
        self.inbox, self.index = root / "inbox", root / "index"


def batch(tmp_path, files, **kw):
    cfg = Cfg(tmp_path, **kw)
    work = tmp_path / "work"
    (work / "md").mkdir(parents=True)
    cfg.index.mkdir()
    state = State(work / "state.sqlite")
    for rel, body in files.items():
        p = cfg.inbox / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"%PDF-1.4 test")
        tid = state.add(rel, p.stat().st_size)
        (work / "md" / f"{tid}.md").write_text(body, encoding="utf-8")
        state.update(tid, status="done")
    return cfg, state, work


def test_a_set_keeps_its_document_its_plan_goes_aside(tmp_path):
    files = {"Kit/Standard.pdf": text(TITLE, APPROVAL, STANDARD), "Kit/Plan.docx": text(TITLE, PLAN_1, PLAN_2)}
    cfg, state, work = batch(tmp_path, files)
    events, warnings = A.set_aside(cfg, state, work)
    assert len(events) == 1 and warnings == []
    assert (cfg.inbox / "Kit/Standard.pdf").is_file() and not (cfg.inbox / "Kit/Plan.docx").exists()
    assert (cfg.inbox / "_rejected/admin/Kit/Plan.docx").is_file()
    rows = list(csv.reader(open(cfg.inbox / "_rejected/admin/manifest.tsv", encoding="utf-8"), delimiter="\t"))
    assert rows[0][:3] == ["date", "file", "page kinds"] and rows[1][1] == "Kit/Plan.docx"
    assert state.by_rel("Kit/Plan.docx")["status"] == "skipped"
    assert (cfg.index / "intake_events.tsv").is_file()


def test_a_set_of_admin_parts_only_goes_aside_whole(tmp_path):
    files = {"Kit/Title.pdf": text(TITLE, APPROVAL), "Kit/Plan.docx": text(PLAN_1, PLAN_2)}
    cfg, state, work = batch(tmp_path, files)
    events, _ = A.set_aside(cfg, state, work)
    assert len(events) == 2 and not (cfg.inbox / "Kit").exists() or not any((cfg.inbox / "Kit").iterdir())


def test_force_accept_and_switch_off(tmp_path):
    files = {"Plans/Plan.docx": text(PLAN_1, PLAN_2)}
    cfg, state, work = batch(tmp_path, files, admin_accept=["plans/"])
    events, warnings = A.set_aside(cfg, state, work)
    assert events == [] and len(warnings) == 1 and (cfg.inbox / "Plans/Plan.docx").is_file()
    cfg["admin_accept"], cfg["admin_filter"] = [], False
    assert A.set_aside(cfg, state, work) == ([], []) and (cfg.inbox / "Plans/Plan.docx").is_file()


def test_the_base_check_lists_admin_only_documents(tmp_path):
    import json

    (tmp_path / "cards").mkdir()
    (tmp_path / "texts").mkdir()
    card = {
        "code": "N-00001",
        "file": {"source_name": "Doc.pdf", "parts": [{"code": "N-00001-02", "source_name": "Plan.docx"}]},
    }
    (tmp_path / "cards" / "N-00001.json").write_text(json.dumps(card), encoding="utf-8")
    (tmp_path / "texts" / "N-00001.md").write_text(text(STANDARD), encoding="utf-8")
    (tmp_path / "texts" / "N-00001-02.md").write_text(text(PLAN_1, PLAN_2), encoding="utf-8")
    hits = A.scan_library(tmp_path)
    assert [c for c, _ in hits] == ["N-00001-02"]
