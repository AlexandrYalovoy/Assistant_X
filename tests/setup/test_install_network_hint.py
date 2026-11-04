"""Setup.bat stopped on the packages: an antivirus scanning HTTPS (Kaspersky) held files.pythonhosted.org."""

from assistant_x.setup import install


def test_an_online_install_that_fails_names_the_antivirus_and_the_sites():
    hint = install.NETWORK_HINT
    for word in ("SSL", "Kaspersky", "pypi.org", "files.pythonhosted.org", "download.pytorch.org", "Setup.bat once more"):
        assert word in hint
