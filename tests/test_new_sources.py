"""
tests/test_new_sources.py

Unit tests for new regional, vertical, remote, and dedicated visa source adapters:
- We Work Remotely (WWR)
- Computrabajo & Bumeran (Latin America)
- JobStreet (Southeast Asia)
- Bayt & GulfTalent (Middle East)
- Rigzone & Energy Jobline (Energy & Renewables)
- Healthcare Placement (International Nursing / Healthcare)
- Jaabz (Dedicated Visa Source with third-party tagging)
"""
import pytest
from job_radar.sources.weworkremotely import parse_wwr_rss, WeWorkRemotelyAdapter
from job_radar.sources.computrabajo import parse_computrabajo_html, ComputrabajoAdapter
from job_radar.sources.bumeran import parse_bumeran_html, BumeranAdapter
from job_radar.sources.jobstreet import parse_jobstreet_html, JobStreetAdapter
from job_radar.sources.bayt import parse_bayt_html, BaytAdapter
from job_radar.sources.gulftalent import parse_gulftalent_html, GulfTalentAdapter
from job_radar.sources.rigzone import parse_rigzone_html, RigzoneAdapter
from job_radar.sources.energyjobline import parse_energyjobline_html, EnergyJoblineAdapter
from job_radar.sources.healthcare_placement import parse_healthjobsuk_html, HealthcarePlacementAdapter
from job_radar.sources.jaabz import parse_jaabz_html, JaabzAdapter
from job_radar.sources.registry import SOURCE_REGISTRY


SAMPLE_WWR_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>We Work Remotely</title>
    <link>https://weworkremotely.com</link>
    <item>
      <title>Automattic: Senior Python Backend Engineer</title>
      <link>https://weworkremotely.com/remote-jobs/automattic-senior-python-backend-engineer</link>
      <description><![CDATA[<p>We are looking for a Senior Backend Engineer to join our team. Visa support and relocation assistance provided.</p>]]></description>
      <pubDate>Mon, 01 Sep 2026 00:00:00 +0000</pubDate>
      <guid>https://weworkremotely.com/remote-jobs/12345</guid>
    </item>
  </channel>
</rss>
"""

SAMPLE_COMPUTRABAJO_HTML = """
<html>
  <body>
    <article class="box_offer" data-id="98765">
      <h2 class="js-o-link"><a href="/ofertas-de-trabajo/oferta-de-trabajo-de-desarrollador-fullstack-98765">Desarrollador Full Stack Python</a></h2>
      <p class="it-blank">Globant Colombia</p>
      <p class="loc">Bogotá, D.C. - Remoto</p>
      <p class="desc">Buscamos desarrollador con experiencia en React y Python.</p>
    </article>
  </body>
</html>
"""

SAMPLE_BUMERAN_HTML = """
<html>
  <body>
    <div class="CardAviso">
      <a href="/empleos/ingeniero-de-software-111222.html">Ingeniero de Software Senior</a>
      <h3 class="company">Mercado Libre</h3>
      <span class="location">Buenos Aires, Argentina</span>
    </div>
  </body>
</html>
"""

SAMPLE_JOBSTREET_HTML = """
<html>
  <body>
    <article>
      <h1 data-automation="jobTitle"><a href="/en/job/lead-data-engineer-778899">Lead Data Engineer</a></h1>
      <span data-automation="jobCompany">Grab Singapore</span>
      <span data-automation="jobLocation">Singapore (Central)</span>
      <div data-automation="jobShortDescription">Scale petabyte data infrastructure across Southeast Asia. EP sponsorship available.</div>
    </article>
  </body>
</html>
"""

SAMPLE_BAYT_HTML = """
<html>
  <body>
    <li data-js-job="1">
      <h2 class="jb-title"><a href="/en/uae/jobs/cloud-solutions-architect-554433/">Cloud Solutions Architect</a></h2>
      <b class="jb-company">Emirates Group</b>
      <span class="jb-loc">Dubai, UAE</span>
      <div class="jb-descr">Lead enterprise cloud migration in AWS and Azure. Full UAE residency visa provided.</div>
    </li>
  </body>
</html>
"""

SAMPLE_GULFTALENT_HTML = """
<html>
  <body>
    <table>
      <tr class="job-row">
        <td><a href="/jobs/senior-petroleum-engineer-332211">Senior Petroleum Engineer</a></td>
        <td><span class="company">Saudi Aramco</span></td>
        <td><span class="location">Dhahran, Saudi Arabia</span></td>
      </tr>
    </table>
  </body>
</html>
"""

SAMPLE_RIGZONE_HTML = """
<html>
  <body>
    <div class="job-item">
      <a href="/jobs/postings/offshore-drilling-engineer-445566">Offshore Drilling Engineer</a>
      <span class="company">SLB (Schlumberger)</span>
      <span class="location">Aberdeen, UK</span>
      <p class="description">Offshore drilling operations. Skilled worker visa eligible.</p>
    </div>
  </body>
</html>
"""

SAMPLE_ENERGY_JOBLINE_HTML = """
<html>
  <body>
    <ul>
      <li class="lister__item">
        <a href="/job/wind-turbine-blade-engineer-998877">Wind Turbine Blade Engineer</a>
        <span class="company">Vestas Wind Systems</span>
        <span class="location">Aarhus, Denmark</span>
        <p class="summary">Design next-generation offshore wind blades.</p>
      </li>
    </ul>
  </body>
</html>
"""

SAMPLE_HEALTHCARE_HTML = """
<html>
  <body>
    <article class="job-result">
      <h2 class="title"><a href="/job/registered-nurse-icu-112233">Registered Nurse - Critical Care (Band 5)</a></h2>
      <span class="trust">Guy's and St Thomas' NHS Foundation Trust</span>
      <span class="location">London, UK</span>
      <p class="summary">Band 5 Staff Nurse role. UK Health and Care Worker Visa Sponsorship provided with OSCE training package.</p>
    </article>
  </body>
</html>
"""

SAMPLE_JAABZ_HTML = """
<html>
  <body>
    <div class="job-card">
      <a href="/job/senior-rust-distributed-systems-engineer-443322">Senior Rust Distributed Systems Engineer</a>
      <h3 class="company">Kraken</h3>
      <span class="location">London, United Kingdom</span>
      <p class="desc">High-throughput crypto engine developer. Visa sponsorship tagged by Jaabz.</p>
    </div>
  </body>
</html>
"""


def test_we_work_remotely_parser():
    jobs = parse_wwr_rss(SAMPLE_WWR_RSS)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "weworkremotely"
    assert job.company == "Automattic"
    assert job.title == "Senior Python Backend Engineer"
    assert job.is_remote is True
    assert "automattic-senior-python-backend-engineer" in job.apply_url


def test_computrabajo_parser():
    jobs = parse_computrabajo_html(SAMPLE_COMPUTRABAJO_HTML, country_code="CO", base_url="https://co.computrabajo.com")
    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "computrabajo"
    assert "Globant" in job.company
    assert "Desarrollador Full Stack Python" in job.title
    assert job.country == "CO"
    assert job.is_remote is True


def test_bumeran_parser():
    jobs = parse_bumeran_html(SAMPLE_BUMERAN_HTML, country_code="AR")
    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "bumeran"
    assert "Mercado Libre" in job.company
    assert "Ingeniero de Software Senior" in job.title
    assert job.country == "AR"


def test_jobstreet_parser():
    jobs = parse_jobstreet_html(SAMPLE_JOBSTREET_HTML, country_code="SG", base_url="https://www.jobstreet.com.sg")
    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "jobstreet"
    assert "Grab" in job.company
    assert "Lead Data Engineer" in job.title
    assert job.country == "SG"


def test_bayt_parser():
    jobs = parse_bayt_html(SAMPLE_BAYT_HTML, country_code="AE")
    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "bayt"
    assert "Emirates Group" in job.company
    assert "Cloud Solutions Architect" in job.title
    assert job.country == "AE"


def test_gulftalent_parser():
    jobs = parse_gulftalent_html(SAMPLE_GULFTALENT_HTML, country_code="SA")
    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "gulftalent"
    assert "Saudi Aramco" in job.company
    assert "Senior Petroleum Engineer" in job.title
    assert job.country == "SA"


def test_rigzone_parser():
    jobs = parse_rigzone_html(SAMPLE_RIGZONE_HTML)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "rigzone"
    assert "Schlumberger" in job.company or "SLB" in job.company
    assert "Offshore Drilling Engineer" in job.title


def test_energyjobline_parser():
    jobs = parse_energyjobline_html(SAMPLE_ENERGY_JOBLINE_HTML)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "energyjobline"
    assert "Vestas" in job.company
    assert "Wind Turbine Blade Engineer" in job.title


def test_healthcare_placement_parser():
    jobs = parse_healthjobsuk_html(SAMPLE_HEALTHCARE_HTML, country_code="UK")
    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "healthcare_placement"
    assert "Guy's and St Thomas'" in job.company
    assert "Registered Nurse" in job.title
    assert job.country == "UK"


def test_jaabz_parser():
    jobs = parse_jaabz_html(SAMPLE_JAABZ_HTML, default_country="UK")
    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "jaabz"
    assert "Kraken" in job.company
    assert "Senior Rust Distributed Systems Engineer" in job.title
    assert job.country == "UK"


def test_all_new_adapters_registered_in_source_registry():
    new_names = [
        "weworkremotely",
        "computrabajo",
        "bumeran",
        "jobstreet",
        "bayt",
        "gulftalent",
        "rigzone",
        "energyjobline",
        "healthcare_placement",
        "jaabz",
    ]
    for name in new_names:
        assert name in SOURCE_REGISTRY, f"Adapter '{name}' must be registered in SOURCE_REGISTRY"
        adapter_cls = SOURCE_REGISTRY[name]
        adapter = adapter_cls()
        assert adapter.name == name
