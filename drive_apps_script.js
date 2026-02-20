/**
 * YJ Partners - Google Drive 자동 분류 & 폴더 정리
 * Google Apps Script에 붙여넣고 실행하세요
 * 삭제 없음 / 애매한 건 99_기타로
 */

function organizeDrive() {
  const root = DriveApp.getRootFolder();

  // 루트 폴더 생성
  const mainFolder = getOrCreateFolder(root, 'YJ Partners - 프로젝트 관리');

  // 카테고리 폴더 생성
  const categories = {
    '01_배포사이트_소스코드': {
      keywords: ['alpha','engine','yjtax','tax master','wonwill','제안서','founderone','파운더원','통합db','db자동화','naver-blog','블로그마스터','index.html','alpha-v4'],
      folder: null
    },
    '02_쇼츠팩토리': {
      keywords: ['shorts','factory','쇼츠','영상제작','render','tts','subtitle','server.py'],
      folder: null
    },
    '03_프랜차이즈_자료': {
      keywords: ['프랜차이즈','franchise','창업','가맹','본사','상권','컨설팅','양도','매각','인테리어','임대','리스','렌탈'],
      folder: null
    },
    '04_세무_회계': {
      keywords: ['세무','세금','tax','부가세','매입','매출','의제','절세','회계','국세','nts','사업자','부가가치'],
      folder: null
    },
    '05_마케팅_영업': {
      keywords: ['마케팅','marketing','영업','블로그','blog','seo','키워드','광고','sns','홍보','cta','포스팅'],
      folder: null
    },
    '06_고객DB_CRM': {
      keywords: ['고객','customer','crm','상담','원윌','wonwill','db자동화','통합db','문자','aligo','sms'],
      folder: null
    },
    '07_API_설정': {
      keywords: ['api','key','token','env','config','설정','credential','oauth','gemini','claude','perplexity','openclaw'],
      folder: null
    },
    '08_이미지_미디어': {
      extensions: ['png','jpg','jpeg','gif','svg','mp4','mp3','wav','webp','ico','bmp','avi','mov'],
      folder: null
    },
    '09_문서_기획': {
      keywords: ['기획','스펙','spec','plan','readme','handoff','프로젝트','명령어','전달'],
      extensions: ['md','txt','pdf','docx','xlsx','pptx','hwp'],
      folder: null
    },
    '99_기타': {
      keywords: [],
      folder: null
    }
  };

  // 카테고리 폴더 생성
  for (const catName in categories) {
    categories[catName].folder = getOrCreateFolder(mainFolder, catName);
    Logger.log('📁 폴더: ' + catName);
  }

  // 루트의 파일 정리
  let movedCount = 0;
  const rootFiles = root.getFiles();

  while (rootFiles.hasNext()) {
    const file = rootFiles.next();
    const fileName = file.getName().toLowerCase();
    const ext = fileName.split('.').pop();

    let targetCat = '99_기타';

    // 확장자로 분류
    for (const catName in categories) {
      const cat = categories[catName];
      if (cat.extensions && cat.extensions.indexOf(ext) >= 0) {
        targetCat = catName;
        break;
      }
    }

    // 키워드로 분류 (우선)
    if (targetCat === '99_기타') {
      for (const catName in categories) {
        const cat = categories[catName];
        if (!cat.keywords) continue;
        for (let i = 0; i < cat.keywords.length; i++) {
          if (fileName.indexOf(cat.keywords[i].toLowerCase()) >= 0) {
            targetCat = catName;
            break;
          }
        }
        if (targetCat !== '99_기타') break;
      }
    }

    // 이동
    const targetFolder = categories[targetCat].folder;
    targetFolder.addFile(file);
    root.removeFile(file);
    movedCount++;
    Logger.log('✅ ' + file.getName() + ' → ' + targetCat);
  }

  // 루트의 폴더 정리 (메인 폴더와 카테고리 폴더 제외)
  const rootFolders = root.getFolders();

  while (rootFolders.hasNext()) {
    const folder = rootFolders.next();
    const folderName = folder.getName();

    // 우리가 만든 폴더는 건너뛰기
    if (folderName === 'YJ Partners - 프로젝트 관리') continue;
    if (folderName.match(/^\d{2}_/)) continue;

    const fNameLower = folderName.toLowerCase();
    let targetCat = '99_기타';

    for (const catName in categories) {
      const cat = categories[catName];
      if (!cat.keywords) continue;
      for (let i = 0; i < cat.keywords.length; i++) {
        if (fNameLower.indexOf(cat.keywords[i].toLowerCase()) >= 0) {
          targetCat = catName;
          break;
        }
      }
      if (targetCat !== '99_기타') break;
    }

    const targetFolder = categories[targetCat].folder;
    targetFolder.addFile(folder);
    root.removeFile(folder);
    movedCount++;
    Logger.log('📁 ' + folderName + ' → ' + targetCat);
  }

  Logger.log('\n============================');
  Logger.log('✅ 정리 완료! ' + movedCount + '개 항목 이동');
  Logger.log('============================');
  Logger.log('\n폴더 구조:');
  Logger.log('YJ Partners - 프로젝트 관리/');
  for (const catName in categories) {
    Logger.log('  ' + catName + '/');
  }
}

function getOrCreateFolder(parent, name) {
  const folders = parent.getFoldersByName(name);
  if (folders.hasNext()) {
    return folders.next();
  }
  return parent.createFolder(name);
}
