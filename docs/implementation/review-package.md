# Review package: full local implementation

No git repository or prior application baseline exists. Inspect current files directly; this package identifies owned implementation scope. Reports: corpus-report.md, services-report.md, ui-report.md. Binding user request and contracts.md; plan Tasks1–6 and original design. Root integration additions: service.py, models.py, tests/test_service.py, tests/test_evaluations.py.

- `app.py` sha256 `a143b950beb5d0a8e47cbb1c52c20712a61ef45084c843e012cb5df6b82c47b8`
- `amgen_explorer/teaching.py` sha256 `fe763147e319d1c779149ffece1b4e301b0e7adf1c49208d55208ad8c9eb977e`
- `amgen_explorer/service.py` sha256 `68c4f1e7cdf7323f655ceee4063136c7e523969c35b69a474e6ae929b16aa4db`
- `amgen_explorer/chunking.py` sha256 `94150d20f29c48017f129dfbadea164d2d26c693e74d26816d7ae4f3f05876e5`
- `amgen_explorer/connectivity.py` sha256 `41c559c3294e728b294044cfcdaeca27c3a3a6a47128f9369649e58ca720e434`
- `amgen_explorer/config.py` sha256 `3d0f1c09ef67412aa3997ad2f56c83d7b1041925a7f6f0814ea851e60b2d7126`
- `amgen_explorer/xml_store.py` sha256 `0fe9690629fc721bf061a56c795bc62428e381f0c1eeb4d08b6ef19042469f57`
- `amgen_explorer/models.py` sha256 `5be6be2c01c455928f5724ba35348870d0a4dc151b287451a556ece4cb2393cf`
- `amgen_explorer/__init__.py` sha256 `6b6e86760b040dc7888f38ab05d667d7e933d2b2e82d85cbcfc47496fec202b1`
- `amgen_explorer/review.py` sha256 `8d6b2e714f8e3c1921eda308604a25f4dcb6a0a696e8940bd3bebb5e27263d54`
- `amgen_explorer/extraction.py` sha256 `b372b419ae3ada2c235464d233531179db5675404117542b368a2946ffd6c32d`
- `amgen_explorer/retrieval.py` sha256 `962a8a70f62053289e8056bf4bda6ba9ad8adb0b00d271df20d8cb9161b11bb5`
- `amgen_explorer/indexing.py` sha256 `d946fe53ff125059b35a836be08f10a3b0d7b8b903e446afccc5c81ebc28996c`
- `ui/__init__.py` sha256 `3d4fba4c041a2700f7ddb46006f1a173a6900c05c66bee464d99e3d8d1d9d10f`
- `ui/sources.py` sha256 `9b634340cde24078efb0a9e8a5c4d9179f6238a072bd218dea1556e49bd1c676`
- `ui/common.py` sha256 `cb0d714f2313545ede55cea14f22cf074512bf23d6ffd7ea2bad59c9b3c87fb3`
- `ui/learn.py` sha256 `56f181b29d1eb32df20a7077eef3f277d6f077b11dd52c53aa6ffac4c7474451`
- `ui/explore.py` sha256 `8a4d5ff4b05b012554ace297946676984a631031e3006e809fc7adfdc3256f00`
- `tests/test_retrieval.py` sha256 `782119949e9e092109e39aa80947bbbb99e94700d917e93feb370ff36d666e42`
- `tests/test_app_flows.py` sha256 `1c711e2c45657e32e4efbfad58bf164447fb5dcf5e11ad7db8ddd52c505d342a`
- `tests/test_service.py` sha256 `baf3e8be1592a216c8e0e31bdd21a2b702af666b3eb40944d6808ee197b93075`
- `tests/test_pinecone_setup.py` sha256 `b19ac0e2364bf0a43d84b2fb5498455e5b0f0a4ceed21cef6917f962428fd42d`
- `tests/test_evaluations.py` sha256 `2d6e1e48ddd999aca034559db5508088682ec9de7f92f1f40b216ca19381ac47`
- `tests/test_teaching.py` sha256 `d5c4e2437e093846971f1867a950a56349c32c27d7d487362942d02ef55ce683`
- `tests/test_indexing.py` sha256 `b333d443fe68a3cfac540e21629cb146f8ad547f7cd29e4b83cc5692be81ae72`
- `tests/test_config.py` sha256 `5241a4ed6a72f99497da951cc1927039b43869a155a56ba92bfd5bf14d16d55f`
- `tests/test_review_and_chunking.py` sha256 `286ca7530546f4baed9794f5a4824f0cbb0927676db0b610c9ab6a1002305992`
- `tests/test_connectivity.py` sha256 `fc258b4e47190c7e8b3f304a2dd28265231435552d863c9d6c8a3d11801fa027`
- `tests/test_xml_pipeline.py` sha256 `eaf7459e2dc9ecd90d536b6f5d2284b40a1d85a3fd89400bfc28a3f142d431f7`

Known explicit limitations: source-fidelity demo not clinicalsignoff; only4MOApassagesreviewed; noOCR; conservativetokenupperbounds withhardbytecap; broad50questioncases are not clinician-reviewed. ExistingamgenproductindexusesEND immutable;localguardpreventsanytext>2040bytes upload/query.
