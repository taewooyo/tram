# Android 프로젝트 연결 예시

기존 프로젝트의 프로필·컨벤션을 보존했다. Tram 기본 스택이 아니다.
실제 대상의 모듈·테스트 경로·Gradle task를 검토해 `.tram/project.json` 설정에 반영한다.
`contextMappings.card`도 대상 프로젝트 안의 실제 카드 경로로 수정한다.
프로필 발견은 테스트 실행·파일 변경 권한을 뜻하지 않는다.
