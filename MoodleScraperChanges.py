# -*- coding: utf-8 -*-
import configparser
import requests
import sqlite3
import pyperclip
import concurrent.futures
from bs4 import BeautifulSoup
from dataclasses import dataclass


CHECKED_URLS = set()


PARSER_ALL = "all"
PARSER_OLDER = "older"
PARSER_NEW = "new"
PARSER_SECTION = "section"
PARSER_OLDER_AND_SECTION = "older and section"


@dataclass
class CourseConfig:
    id : str
    name : str
    parser : str


@dataclass
class ScrappedResult:
    course_url : str
    course_id : str
    course_name : str
    texts : list


def moodle_session(file="MoodleSession.txt"):
    with open(file, "r") as file:
        return file.read().strip()


def config_dict(file="config.ini"):
    config = configparser.ConfigParser()
    config.read(file)
    settings = config["SETTINGS"]

    url = settings.get("MoodleURL")

    if not url:
        raise AssertionError("MoodleURL must be valid. Check config.ini.")

    return {
        "database" : settings.get("Database", fallback="database.db"),
        "courses_file" : settings.get("CoursesFile", fallback="Courses.txt"),
        "url" : url,
    }


def courses_from_file(file):
    courses = []
    with open(file, "r", encoding="UTF-8") as file:
        for line in file:
            course_id, course_name, parser = line.split(" ; ")
            courses.append(
                CourseConfig(
                    course_id.strip(),
                    course_name.strip(),
                    parser.strip().lower()
                )
            )
    return courses


class DatabaseConnection:
    def __init__(self, file):
        self.file = file
        self.conn = None

    def __enter__(self):
        self.conn = sqlite3.connect(self.file)
        return self.conn.cursor()

    def __exit__(self, type_, value, traceback):
        if self.conn:
            self.conn.commit()
            self.conn.close()

    @classmethod
    def exists_database_table(cls, cursor, table):
        cursor.execute("SELECT count(name) FROM sqlite_master WHERE type='table' AND name=?", (table,))
        return cursor.fetchone()[0] == 1


class UrlScrapper:

    def __init__(self, session, course_url, course_id, course_name, parser_type):
        self.session = session
        self.course_url = course_url
        self.course_id = course_id
        self.course_name = course_name
        self.parser_type = parser_type

        self.use_older_parser = parser_type == PARSER_OLDER or parser_type == PARSER_OLDER_AND_SECTION or parser_type == PARSER_ALL
        self.use_sections_parser = parser_type == PARSER_SECTION or parser_type == PARSER_OLDER_AND_SECTION or parser_type == PARSER_ALL
        self.use_new_parser = parser_type == PARSER_NEW or parser_type == PARSER_ALL

        self.checked_urls = set()

    def scrapper(self, url):
        self.checked_urls.add(url)

        req = self.session.get(url)
        if req.status_code == 200:
            soup = BeautifulSoup(req.text, "html.parser")

            course_contents = soup.find_all("div", class_="course-content")
            if len(course_contents) != 1:
                raise AssertionError("Error, invalid credentials: len(course_contents) != 1")

            texts = []

            topics_elems = course_contents[0].find_all("ul", class_="topics")
            if len(topics_elems) >= 1:
                if self.use_older_parser: # old style
                    for topic_elem in topics_elems:
                        texts.extend(self.parse_old(topic_elem))
                if self.use_sections_parser: # check sections
                    texts.extend(self.parse_sections(topics_elems[0]))
            elif len(topics_elems) == 0:
                if self.use_new_parser: # new style
                    texts.extend(self.parse_new(course_contents[0]))

            return ScrappedResult(url, self.course_id, self.course_name, texts)
        else:
            print(f"Error, URL {url} returned status code {req.status_code}")


    def parse_old(self, topics_elem):
        lis = topics_elem.find_all("li")
        if len(lis) <= 0:
            raise AssertionError("Error, maybe invalid credentials? len(lis) <= 0")

        texts = []
        for li in lis:
            contents = li.find_all("div", class_="content")
            if len(contents) > 0:
                text = contents[0].text
                texts.append(text)

        return texts


    def parse_sections(self, topics_elem):
        section_name = topics_elem.find_all("h3", class_="sectionname")
        section_title = topics_elem.find_all("h4", class_="section-title")

        sections = section_name + section_title

        texts = []
        for sec in sections:
            for a in sec.find_all('a', href=True):
                href = a['href']
                if href not in self.checked_urls:
                    print(f"[i] Recursively checking: {href}")
                    texts.extend(self.scrapper(href).texts)

        return texts


    def parse_new(self, course_content):
        texts = []

        for content in course_content.find_all("div", class_="content"):
            activities = content.find_all("li", class_="activity")
            for activity in activities:
                text = activity.text
                texts.append(text)

        for a in course_content.find_all('a', href=True):
            href = a['href'].replace("§ion=", "&section=")
            if self.course_url in href and href not in self.checked_urls:
                print(f"[i] Recursively checking: {href}")
                texts.extend(self.scrapper(href).texts)

        return texts


def do_scrapper(session, course_url, course_id, course_name, parser_type):
    scrapper = UrlScrapper(session, course_url, course_id, course_name, parser_type)
    return scrapper.scrapper(course_url)


class MoodleScraper:

    def __init__(self, url, database_file, cookies):
        self.cookies = cookies
        self.base_url = url
        self.database_file = database_file
        self.log_parts = []
        self.found = False

    def scraper(self, courses):
        with requests.Session() as session:
            for k, v in self.cookies.items():
                session.cookies[k] = v

            with concurrent.futures.ThreadPoolExecutor(max_workers=max(len(courses), 8)) as executor:
                futures = (
                    executor.submit(do_scrapper, session, f"{self.base_url}course/view.php?id={c.id}", c.id, c.name, c.parser)
                    for c in courses
                )
                for future in concurrent.futures.as_completed(futures):
                    try:
                        data = future.result()
                        self.update_database(data.course_id, data.course_name, data.texts)
                    except Exception as exc:
                         print(f"Error at future completion:\n{exc}")

        return self.generate_log()

    def update_database(self, course_id, course_name, texts):
        table_name = f"courseid_{course_id}"  # must not start with a number.

        with DatabaseConnection(self.database_file) as db:
            if not DatabaseConnection.exists_database_table(db, table_name):
                db.execute(f"CREATE TABLE {table_name} (content TEXT UNIQUE)")

            db.execute(f"SELECT * FROM {table_name}")
            results = set([r[0] for r in db.fetchall()])

            added_course_name = False

            for text in texts:
                if (text not in results) and (text not in self.log_parts):
                    db.execute(f"INSERT INTO {table_name} VALUES (?)", (text,))

                    if not added_course_name:
                        self.log_parts.append(f"Matéria: {course_name}")
                        added_course_name = True
                        self.found = True

                    self.log_parts.append(text)

    def generate_log(self):
        def clean_extra(text):
            replace_pairs = [  # list, preserve order
                ["completo", ""],
                ["Não concluído", ""],
                ["Progresso do curso", ""],
                ["Seu progresso", ""],
                ["\n\n", "\n"],
            ]
            for pair in replace_pairs:
                while pair[0] in text:
                    text = text.replace(pair[0], pair[1])

            return text.strip()

        return "\n---------\n".join([f"\"{clean_extra(t)}\"" for t in self.log_parts])


if __name__ == "__main__":

    try:
        configs = config_dict()

        database = configs["database"]
        courses_file = configs["courses_file"]
        url = configs["url"]

        courses = courses_from_file(courses_file)

        cookies = { "MoodleSession" : moodle_session() }
        scraper = MoodleScraper(url=url, database_file=database, cookies=cookies)

        log = scraper.scraper(courses)

        if scraper.found:
            print(log)
            pyperclip.copy(f"As seguintes alterações no Moodle foram encontradas:\n\n{log}")
        else:
            print("Nothing new found.")
            pyperclip.copy("Nothing new found.")
    except Exception as error:
        print("\nError:\n")
        print(error)

    input("\n\nPress ENTER to exit.")
