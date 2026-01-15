# CRG – Coding Rules & Guidelines (ImgToPDF)

## 1. 언어 및 환경
- Python 3.10+
- Windows 환경 기준 개발

## 2. 구조 규칙
- 단일 진입점: `ImgToPDF.py`
- GUI / 로직 분리 원칙 유지
- 상태 관리는 `SelectionState` dataclass 사용

## 3. 네이밍 규칙
- 함수/변수: snake_case
- 클래스: PascalCase
- 상수: UPPER_SNAKE_CASE

## 4. GUI 규칙
- Tkinter + ttk 사용
- 모든 사용자 동작은 버튼/다이얼로그 기반
- 메시지는 `messagebox` 또는 전용 팝업으로 처리

## 5. 에러 처리
- 사용자 오류: messagebox 경고
- 시스템 오류: try/except 후 메시지 표시
- 프로그램 강제 종료 금지

## 6. 외부 라이브러리 사용 규칙
- img2pdf: 이미지 재인코딩 금지 목적
- Pillow: 메타데이터/크기 확인용
- tkinterdnd2: 선택적 의존성

## 7. 패키징 규칙
- requirements.txt 필수
- PyInstaller spec 파일 유지
- hidden-import 명시

## 8. 확장 시 주의사항
- 이미지 처리 로직 변경 시 화질 영향 검증 필수
- OS 확장 시 파일 열기 로직 분기 필요
