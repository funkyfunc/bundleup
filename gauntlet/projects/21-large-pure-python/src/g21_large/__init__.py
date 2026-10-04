"""Gauntlet 21: a large amount of pure-Python code, plus the data files it reads at run time."""
import sys


def main() -> int:
    # sympy: ~1,600 modules, imported lazily as features are used.
    import sympy

    x = sympy.symbols("x")
    assert sorted(sympy.solve(x**2 - 4, x)) == [-2, 2]
    assert sympy.integrate(sympy.cos(x), x) == sympy.sin(x)

    # Django: templates plus translation catalogs (.mo files located relative to the package).
    import django
    from django.conf import settings

    settings.configure(USE_I18N=True, LANGUAGE_CODE="en", TEMPLATES=[
        {"BACKEND": "django.template.backends.django.DjangoTemplates"}])
    django.setup()
    from django.template import engines
    from django.utils import translation
    from django.utils.dates import MONTHS

    html = engines["django"].from_string("{% for n in items %}<{{ n|upper }}>{% endfor %}").render(
        {"items": ["a", "b"]})
    assert html == "<A><B>", html
    with translation.override("de"):
        assert str(MONTHS[1]) == "Januar", str(MONTHS[1])

    # boto3: service models are JSON data inside botocore. Nothing here touches the network.
    import boto3

    s3 = boto3.client("s3", region_name="us-east-1", aws_access_key_id="AKIAEXAMPLE",
                      aws_secret_access_key="example-secret")
    assert "PutObject" in s3.meta.service_model.operation_names
    url = s3.generate_presigned_url("get_object", Params={"Bucket": "b", "Key": "k"}, ExpiresIn=60)
    assert "Signature" in url, url

    # networkx: a plain algorithm over pure-Python data structures.
    import networkx as nx

    graph = nx.Graph([("a", "b"), ("b", "c"), ("c", "d"), ("a", "d"), ("d", "e")])
    assert nx.shortest_path(graph, "a", "e") == ["a", "d", "e"]

    loaded = [m for m in sys.modules if m.split(".")[0] in ("sympy", "django", "botocore", "boto3", "networkx")]
    print(f"modules_loaded={len(loaded)}")
    print("GAUNTLET OK 21-large-pure-python")
    return 0
