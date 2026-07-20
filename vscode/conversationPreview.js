const path = require('path');
const vscode = require('vscode');

class PreviewStore {
  constructor(vscodeApi = vscode) {
    this.vscode = vscodeApi;
    this.contents = new Map();
    this.changeSets = new Map();
  }

  put(sessionId, changeSetId, files) {
    this.deleteChangeSet(sessionId, changeSetId);
    const labels = relativeLabels(files.map(file => file.uri));
    const descriptors = files
      .map((file, index) => {
        const base = [
          'modelable-preview:',
          encodeURIComponent(sessionId),
          encodeURIComponent(changeSetId),
          encodeURIComponent(file.uri),
        ].join('/');
        const suffix = previewSuffix(file.uri);
        const beforeUri = this.vscode.Uri.parse(`${base}/before${suffix}`);
        const afterUri = this.vscode.Uri.parse(`${base}/after${suffix}`);
        this.contents.set(beforeUri.toString(), file.beforeText);
        this.contents.set(afterUri.toString(), file.afterText);
        return {
          sourceUri: file.uri,
          label: labels[index],
          existedBefore: file.existedBefore,
          beforeUri,
          afterUri,
        };
      })
      .sort((left, right) => left.label.localeCompare(right.label));
    this.changeSets.set(changeSetKey(sessionId, changeSetId), descriptors);
    return descriptors;
  }

  provideTextDocumentContent(uri) {
    return this.contents.get(uri.toString());
  }

  deleteChangeSet(sessionId, changeSetId) {
    const key = changeSetKey(sessionId, changeSetId);
    for (const descriptor of this.changeSets.get(key) ?? []) {
      this.contents.delete(descriptor.beforeUri.toString());
      this.contents.delete(descriptor.afterUri.toString());
    }
    this.changeSets.delete(key);
  }

  deleteSession(sessionId) {
    const prefix = `${sessionId}\0`;
    for (const key of [...this.changeSets.keys()]) {
      if (key.startsWith(prefix)) {
        const changeSetId = key.slice(prefix.length);
        this.deleteChangeSet(sessionId, changeSetId);
      }
    }
  }

  hasSession(sessionId) {
    const prefix = `${sessionId}\0`;
    return [...this.changeSets.keys()].some(key => key.startsWith(prefix));
  }

  async showDiff(sessionId, changeSetId) {
    const descriptors = this.changeSets.get(
      changeSetKey(sessionId, changeSetId),
    ) ?? [];
    if (descriptors.length === 0) {
      throw new Error(
        'This Modelable preview is no longer available. Request a fresh preview.',
      );
    }
    let selected = descriptors[0];
    if (descriptors.length > 1) {
      const pick = await this.vscode.window.showQuickPick(
        descriptors.map(descriptor => ({
          label: descriptor.label,
          descriptor,
        })),
        { placeHolder: 'Select a Modelable preview file' },
      );
      if (!pick) {
        return;
      }
      selected = pick.descriptor;
    }
    await this.vscode.commands.executeCommand(
      'vscode.diff',
      selected.beforeUri,
      selected.afterUri,
      `${selected.label} — Modelable change ${changeSetId}`,
      { preview: true },
    );
  }
}

function changeSetKey(sessionId, changeSetId) {
  return `${sessionId}\0${changeSetId}`;
}

function relativeLabels(uris) {
  const paths = uris.map(uri => {
    try {
      return decodeURIComponent(new URL(uri).pathname)
        .replace(/^\/([A-Za-z]:)/, '$1')
        .replaceAll('\\', '/');
    } catch {
      return uri.replaceAll('\\', '/');
    }
  });
  if (paths.length === 0) {
    return [];
  }
  const common = commonDirectory(paths);
  return paths.map(filePath =>
    path.posix.relative(common, filePath) || path.posix.basename(filePath));
}

function commonDirectory(paths) {
  let common = path.posix.dirname(paths[0]);
  for (const filePath of paths.slice(1)) {
    while (
      filePath !== common &&
      !filePath.startsWith(`${common}/`)
    ) {
      const parent = path.posix.dirname(common);
      if (parent === common) {
        return common;
      }
      common = parent;
    }
  }
  return common;
}

function previewSuffix(uri) {
  try {
    const suffix = path.posix.extname(decodeURIComponent(new URL(uri).pathname));
    if (/^\.[A-Za-z0-9][A-Za-z0-9._+-]*$/.test(suffix)) {
      return suffix;
    }
  } catch {
    // Fall through to a neutral text suffix for malformed source URIs.
  }
  return '.txt';
}

module.exports = {
  PreviewStore,
  previewSuffix,
  relativeLabels,
};
