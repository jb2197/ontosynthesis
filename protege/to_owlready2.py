import glob
import os.path
import pathlib
import re
import shutil
from collections import defaultdict

from loguru import logger
from owlready2 import Ontology, ObjectPropertyClass, ThingClass, onto_path, get_ontology
from pandas._typing import FilePath


def remove_text_in_brackets(text):
    opening_braces = '\(\['
    closing_braces = '\)\]'
    non_greedy_wildcard = '.*?'
    return re.sub(f'[{opening_braces}]{non_greedy_wildcard}[{closing_braces}]', '', text)


def lookup(lines: list[str], tag: str):
    tag_start = f"<{tag}>"
    tag_end = f"</{tag}>"
    tag_contents = []
    for i, line in enumerate(lines):
        if line.strip().startswith(tag_start):
            found_close = False
            for j in range(800):
                if lines[i + j].strip().endswith(tag_end):
                    found_close = True
                    break
            if not found_close:
                raise RuntimeError(f"cannot find closure for: {tag} at line: {i}")
            tag_content = lines[i: i + j + 1]
            tag_contents.append(tag_content)
    return tag_contents


def parse_annotation_assertion_lines(lines: list[str]):
    content = lines[1: -1]
    pref_label = """<AnnotationProperty IRI="http://www.w3.org/2004/02/skos/core#prefLabel"/>"""
    definition = """<AnnotationProperty IRI="http://www.w3.org/2004/02/skos/core#definition"/>"""
    if content[0].strip() == pref_label:
        key = "pref_label"
    elif content[0].strip() == definition:
        key = "definition"
    else:
        raise ValueError
    iri = lookup(content, tag="IRI")
    assert len(iri) == 1
    iri = iri[0][0]
    literal = lookup(content, tag="Literal")
    assert len(literal) == 1
    literal = literal[0][0]

    iri = iri.strip().lstrip("<IRI>").rstrip("</IRI>")
    literal = literal.strip()[len("<Literal>"): -len("</Literal>")]
    logger.warning(f"found: {iri}\n{key}: {literal}")
    return iri, key, literal


def parse_owx(filepath: FilePath):
    with open(filepath, "r") as f:
        lines = f.readlines()

    data = defaultdict(dict)
    list_of_annotation_assertion_lines = lookup(lines, "AnnotationAssertion")
    for lines in list_of_annotation_assertion_lines:
        try:
            iri, key, literal = parse_annotation_assertion_lines(lines)
        except ValueError:
            continue
        data[iri][key] = literal
    return data


def to_camel_case(snake_str):
    return "".join(x.capitalize() for x in snake_str.lower().split("_"))


def is_legal_python_name(name: str):
    if all(c.isalpha() or c == "_" for c in name):
        return True
    return False


def export_python_class(onto: Ontology, definition: str, class_name: str, iri: str, suffix: str = ""):
    cls = onto.search_one(iri=iri)
    if suffix != "":
        suffix = "__" + suffix

    if isinstance(cls, ObjectPropertyClass):
        python_class_name = class_name.replace(" ", "_") + suffix
    elif isinstance(cls, ThingClass):
        python_class_name = class_name.replace(" ", "_")
        python_class_name = to_camel_case(python_class_name) + suffix
    else:
        raise TypeError
    python_class_name = python_class_name.strip().replace("(", "_").replace(")", "")
    # if "(" in python_class_name and ")" in python_class_name:
    #     python_class_name = remove_text_in_brackets(python_class_name).strip().strip("_")
    if not is_legal_python_name(python_class_name):
        raise TypeError
    template = f"""
{python_class_name} = onto.search_one(iri="{iri}")
# {definition}
    """
    return template, python_class_name


def export_owlready2(onto: Ontology, data: dict[str, dict]):
    doc = """
from owlready2 import onto_path, get_ontology
onto_path.append("/home/qai/workplace/ontosynthesis/protege/ontologies")
onto = get_ontology("file:///home/qai/workplace/ontosynthesis/protege/owx_dump/afo.owx").load()
    """
    registered_class_name = set()
    for iri in data:
        try:
            onto_class_name = data[iri]['pref_label']
            definition = data[iri]['definition']
        except KeyError:
            continue
        if "#" in iri:
            suffix = iri.split("#")[-1]
        else:
            suffix = iri.split("/")[-1]

        if onto_class_name not in registered_class_name:
            suffix = ""
        try:
            s, python_class_name = export_python_class(onto, definition, onto_class_name, iri, suffix=suffix)
        except TypeError:
            continue
        registered_class_name.add(onto_class_name)
        doc += s
    return doc


if __name__ == '__main__':

    this_dir = os.path.dirname(__file__)
    dump_dir = os.path.join(this_dir, "owx_dump")
    output_dir = os.path.join(this_dir, "ontologies")
    onto_path.append(dump_dir)
    ONTO = get_ontology(f"file://{dump_dir}/afo.owx").load()
    shutil.rmtree(output_dir, ignore_errors=True)
    pathlib.Path(output_dir).mkdir(exist_ok=True)

    import_strings = []

    for fn in glob.glob(f"{dump_dir}/*.owx"):
        basename = os.path.basename(fn)
        module_name = basename[:-4].replace("-", "_")
        owx_data = parse_owx(fn)
        code = export_owlready2(ONTO, owx_data)
        with open(f"{output_dir}/{module_name}.py", "w") as f:
            f.write(code)
        import_sting = f"from .{module_name} import *"
        import_strings.append(import_sting)

    with open(f"{output_dir}/__init__.py", "w") as f:
        f.write("\n".join(import_strings))
