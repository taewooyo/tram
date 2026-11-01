# Python / pytest-cov 어댑터

이 어댑터는 `coverage.adapter`가 `python-pytest-cov`인 프로젝트에서 선택한다. 신규 `.tram/project.json`에 coverage가 없으면 중단한다. `.tram/project.json`이 없는 legacy `.codex/project-profile.json` 호환 호출에서만 미설정 Python 기본값을 보존한다.

## 입력·환경 및 실행 정보

1. 입력은 `/coverage [목표%] [대상]`이다. 신규 프로필은 목표·소스 대상·테스트 허용 경로를 명시한다. legacy 호환 호출의 기본 목표는 `85`, 기본 대상은 `app/`이다. 목표가 0~100 범위를 벗어나거나 대상 경로가 없으면 멈춘다. legacy 예: `/coverage`, `/coverage 90`, `/coverage 85 app/`.
2. 테스트 수정 허용 경로는 신규 프로필의 `coverage.testPaths`를 사용한다. legacy 호환 기본은 `tests/`다. 지정 디렉터리가 없으면 설정 준비가 필요함을 보고한다. 다른 언어의 테스트 경로를 추론하지 않는다.
3. 프로젝트 실행 환경은 `.venv/bin/python`을 우선하고, 없으면 활성 가상환경의 `python`/`python3`를 사용한다. 선택한 환경에서 pytest를 실행할 수 없으면 설치 방법을 안내하고 멈춘다.
4. 선택한 인터프리터에서 `pytest_cov`를 확인한다. 없으면 프로젝트 가상환경 안에서만 `python -m pip install pytest-cov`를 시도한다. 전역 설치를 하지 않으며 설치 실패 시 멈춘다.
5. 위 인터프리터·목표·대상·허용 경로를 공통 실행 정보로 넘긴다. 측정 범위는 지정한 소스 대상, 테스트 범위는 pytest 전체 수집이다. 특정 테스트만 선택하는 필터는 적용하지 않는다.

## 기준선 및 각 라운드의 측정

선택한 인터프리터로 `python -m pytest --cov=<대상> --cov-report=term-missing`을 실행한다. 매번 같은 대상과 명령을 사용하며 테스트 실패나 측정 실패를 통과로 취급하지 않는다.

`python -m coverage json -o -`로 같은 실행의 커버리지 데이터를 읽어 총 실행/미실행 라인과 미실행 위치를 확인한다. 터미널의 반올림된 정수 백분율 대신 원본 라인 수로 목표와 개선을 판정한다. 이전 실행의 데이터나 해석 불가능한 결과는 사용하지 않는다.

기준선부터 라운드 판정·테스트 파일 커밋·롤백·종료 기록은 [상위 SKILL.md의 공통 루프](../SKILL.md#진행)를 따른다. 확정한 테스트 허용 경계를 모든 변경·스테이징·롤백에 적용한다.
