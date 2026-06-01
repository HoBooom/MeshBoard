# Vendored CityLearn Runtime

This directory contains the Python runtime modules and rendering assets from
the official `CityLearn==2.1b12` PyPI source distribution required by the
CHESCA submission.

- Upstream project: https://github.com/intelligent-environments-lab/CityLearn
- PyPI release: https://pypi.org/project/CityLearn/2.1b12/
- Source archive SHA-256:
  `c001657935317166814a4d992da7234404f7afbe7001a7c12b324113f7efdfed`
- Package metadata classifies the upstream project under the MIT License.

The upstream packaged example datasets are intentionally omitted because this
project evaluates the schemas bundled in `CHESCA-main/data/schemas`. No source
changes were made to the copied Python modules.

The module is vendored instead of installed with pip because the upstream
source distribution attempts to read a missing `requirements.txt` during
modern pip metadata generation, and its old pinned scientific dependencies are
not appropriate for current Google Colab runtimes.
