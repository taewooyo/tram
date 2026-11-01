# 기여·일반 오류 제보

질문·사용 피드백·오류는 [GitHub Issues](https://github.com/taewooyo/tram/issues)에 남긴다. 변경에는 범위와 실제 검증 근거를 설명한다. 기여는 [Apache-2.0](LICENSE) 조건으로 제공한다.

일반 제보에는 Tram·host·OS·Python 버전, 기대/실제 동작, 비밀을 제거한 최소 재현 단계, CLI exit와 errorCode, 운영 manifest의 유무를 적는다. 로그 원문을 요구하지 않는다. 민감한 제보는 [보안 안내](SECURITY.md)를 따른다.

정본은 `src/`와 `platform/`이며 생성 package·설치 cache를 직접 수정하지 않는다. 저장소의 `AGENTS.md`와 `OS.md`, `src/context/doc-conventions.md`를 먼저 읽는다. 새 기능·고위험·설계 변경은 PRD 확정·Plan 승인 후 구현한다. 동작 변경은 회귀 검증을 함께 추가한다. 개발 환경과 생성본은 저장소 루트에서 다음과 같이 준비한다.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
python3 scripts/build.py --local
.venv/bin/python -m pytest -q
python3 scripts/build.py --check --local
```

`--local`은 inventory에 기록된 작업용 `.codex` 생성 경로만 동기화하며 목록 밖 legacy 파일은 보존한다. 문서·HTML의 상대 링크를 확인하고 설명 자산은 실제 HTML 렌더와 PNG 직접 확인을 포함한다. 미실행 host/CI 검사는 미검증으로 표시한다. 기여 검토나 일반 제보는 공개 게시·라이선스·지원 약속을 자동 확정하지 않는다.

## CI 실패 조사

CI는 OS·Python 조합을 각각 끝까지 실행하며 job당 최대 30분으로 제한한다. 같은 브랜치에 새 변경이 올라오면 이전 일반 검사 실행은 취소한다. 릴리스 후보 검증은 별도로 실행한다.

실패한 실행의 Actions artifact에서 `tram-tests-<OS>-py<Python>` 또는 `tram-candidate-tests`의 JUnit 보고서를 확인한다. 보고서는 14일 보존하며 테스트가 시작되기 전에 실패하거나 job이 취소되면 없을 수 있다. 테스트 이름·실패 원인을 확인하고 같은 환경에서 재현한 뒤 수정한다. 보고서에는 assertion 내용이 포함될 수 있으므로 테스트에 실제 인증정보나 사용자 데이터를 넣지 않는다. CI 통과와 실제 호스트 설치·재개 검증은 별도 증거로 관리한다.

## 공개 버전 준비

사용자는 공개 저장소의 `build/codex` 또는 `build/claude`를 설치한다. 개발 의존성 설치와 빌드는 기여자 작업이다. 두 패키지의 공통 기능은 `src/`에서 유지하고 호스트별 설치는 각각의 marketplace에서 연결한다.

1. 버전·CHANGELOG·지원 조건과 실제 검증 근거를 정리한다. 라이선스 원문을 두 패키지에 포함한다.
2. 전체 테스트와 `python3 scripts/build.py --check`를 실행한다. 각 실제 호스트에서 설치·작업·재개·업데이트·제거를 확인하고 미실행 항목을 기록한다.
3. `python3 scripts/build.py --archive-dir release/candidate`로 버전별 후보 ZIP·checksum·준비 상태를 만든다. `.github/workflows/release.yml`도 후보를 검사·보관하며 게시하지 않는다.
4. 첫 공개 설명은 [0.0.1 릴리스 초안](https://github.com/taewooyo/tram/blob/main/release/notes-0.0.1.md)을 검토한다. 최종 검증한 소스·생성 패키지를 함께 커밋하고 공개 저장소에 반영한다.
5. 게시 권한을 확인한 뒤 해당 커밋에 `v0.0.1` 태그와 GitHub Release를 만든다. 실제 게시 전 초안을 배포 완료로 표시하지 않는다. 공개 저장소에서 두 호스트의 Git 설치 경로를 다시 확인한다.

라이선스·비공개 보안 제보 설정과 패키지 검사는 실제 에이전트 작업 성공을 대신하지 않는다.
