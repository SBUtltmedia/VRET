/**
 * js/vrm-cdn-helper.js
 * 
 * Helper to resolve VRM model URLs to the external CDN (valid-vrm-avatars)
 * for large model categories that have been removed from the main repository.
 */

(function() {
  const MODEL_CDN = 'https://raw.githubusercontent.com/TLTMedia/valid-vrm-avatars/main/';
  const CATEGORIES = ['AIAN', 'Asian', 'Black', 'Hispanic', 'MENA', 'NHPI', 'White', 'X_Non-validated'];

  /**
   * Resolves a local model path to the external CDN if it belongs to a large category.
   * @param {string} path - The model path (e.g., 'models/AIAN/avatar.vrm')
   * @returns {string} The resolved URL
   */
  window.resolveModelUrl = function(path) {
    if (!path || typeof path !== 'string') return path;
    
    // Normalize path
    let cleanPath = path.replace(/\\/g, '/');
    if (cleanPath.startsWith('./')) cleanPath = cleanPath.slice(2);
    if (cleanPath.startsWith('/')) cleanPath = cleanPath.slice(1);
    
    // Check if it's in a category that moved to the external CDN
    const parts = cleanPath.split('/');
    if (parts[0] === 'models' && parts.length > 2 && CATEGORIES.includes(parts[1])) {
      // Resolve to CDN only if running against the external model set;
      // local repos keep models in ./models/ and should not be redirected.
      return path;
    }
    
    return path;
  };

  // Monkey-patch Babylon.js loaders to automatically resolve URLs
  if (typeof BABYLON !== 'undefined') {
    const SL = BABYLON.SceneLoader;
    if (SL) {
      const originalImportMeshAsync = SL.ImportMeshAsync;
      SL.ImportMeshAsync = function(meshesNames, rootUrl, sceneFilename, scene, onProgress, pluginExtension) {
        // If sceneFilename is not a string, it might be the Scene object (Babylon shortcut)
        const isSceneFileAString = typeof sceneFilename === 'string';
        
        if (!sceneFilename || !isSceneFileAString) {
          rootUrl = window.resolveModelUrl(rootUrl);
        } else {
          // If both are provided and sceneFilename is a string, check the combination
          const combined = rootUrl + (rootUrl.endsWith('/') ? '' : '/') + sceneFilename;
          if (window.resolveModelUrl(combined).startsWith(MODEL_CDN)) {
             const resolved = window.resolveModelUrl(combined);
             rootUrl = '';
             sceneFilename = resolved;
          }
        }
        return originalImportMeshAsync.call(SL, meshesNames, rootUrl, sceneFilename, scene, onProgress, pluginExtension);
      };

      // Also patch the direct BABYLON.ImportMeshAsync if it exists (shortcut)
      if (BABYLON.ImportMeshAsync === originalImportMeshAsync) {
        BABYLON.ImportMeshAsync = SL.ImportMeshAsync;
      }
    }
  }
})();
