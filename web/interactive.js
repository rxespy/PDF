// web/interactive.js
/**
 * Dynamic B2B Administrative Panel state management powered strictly by Alpine.js and PDF.js CDN.
 */

document.addEventListener('alpine:init', () => {
  Alpine.data('app', () => ({
    activeView: 'sandbox', // sandbox, templates, categories, audit, dashboard
    activeTenant: 'co-corporate-global-ae',
    activeTemplateId: 'g12',
    sidebarClosed: false,
    dbLatency: 14,
    syncing: false,

    // Systems datasets
    tenants: [],
    categories: [],
    templates: [],
    auditLogs: [],

    // Filters and Modals
    corrFilter: '',
    showTenantModal: false,
    showCategoryModal: false,
    showTemplateModal: false,

    // Creation inputs
    newTenant: { tenant_id: '', corporate_name: '', tenant_scope: '' },
    newCategory: { category_id: '', name: '', description: '' },
    newTemplate: { template_id: '', name: '' },

    // Core Sandbox variables
    viewerTab: 'mapper', // mapper, preview
    activeFieldToMap: null,
    formInputs: {},
    compiling: false,
    downloadUrl: '',

    // Upload systems
    uploadStatus: 'idle', // idle, uploading, success, failed
    uploadProgress: 0,
    errorMessage: '',
    uploadedRefPath: '',
    uploadedFilename: '',
    uploadedSize: 0,
    dragOver: false,

    // PDF loader trackers
    currentLoadId: 0,
    pdfDoc: null,
    renderTask: null,

    async init() {
      await this.syncDatabaseStates();
      this.syncSandboxInputs();

      // Watch for changes to reload PDF
      this.$watch('activeTemplateId', () => {
        this.syncSandboxInputs();
        this.loadPdfOnCanvas();
      });

      this.$watch('uploadedRefPath', () => {
        this.loadPdfOnCanvas();
      });

      this.loadPdfOnCanvas();
    },

    // Sync database states
    async syncDatabaseStates() {
      this.syncing = true;
      const startTime = Date.now();
      try {
        const [resTenants, resCats, resTpls, resAudits] = await Promise.all([
          fetch('/api/v1/tenants'),
          fetch('/api/v1/categories'),
          fetch('/api/v1/templates'),
          fetch('/api/v1/audit')
        ]);

        if (resTenants.ok) this.tenants = await resTenants.json();
        if (resCats.ok) this.categories = await resCats.json();
        if (resTpls.ok) this.templates = await resTpls.json();
        if (resAudits.ok) this.auditLogs = await resAudits.json();

        this.dbLatency = Date.now() - startTime + 8;
      } catch (err) {
        console.error("Express synchronization pipeline failure: ", err);
      } finally {
        this.syncing = false;
      }
    },

    // Populate missing inputs based on active template
    syncSandboxInputs() {
      const active = this.templates.find(t => t.template_id === this.activeTemplateId) || this.templates[0];
      if (!active) return;
      
      const fields = active.schema_json?.fields_mapping || [];
      fields.forEach(f => {
        if (!(f.field_id in this.formInputs)) {
          this.formInputs[f.field_id] = f.type === 'arabic' ? 'مؤسسة الفطيم للتجارة' : 'REG-83921-AE';
        }
      });
    },

    // Renders the pdf to layout canvas safely
    async loadPdfOnCanvas() {
      const canvas = document.getElementById('sandbox-pdf-canvas');
      if (!canvas) return;

      this.currentLoadId += 1;
      const loadId = this.currentLoadId;

      const url = this.uploadedRefPath 
        ? `/api/v1/document/download/${this.uploadedRefPath}` 
        : `/api/v1/document/download/fallback`;

      // Cancel any running renders
      if (this.renderTask) {
        try {
          this.renderTask.cancel();
        } catch (e) {}
        this.renderTask = null;
      }

      try {
        const pdfjsLib = window.pdfjsLib;
        if (!pdfjsLib) {
          console.warn("pdfjsLib global CDN element is not hydrated yet.");
          return;
        }

        const loadingTask = pdfjsLib.getDocument(url);
        const doc = await loadingTask.promise;
        
        if (loadId !== this.currentLoadId) return;
        this.pdfDoc = doc;

        const page = await doc.getPage(1);
        if (loadId !== this.currentLoadId) return;

        const viewport = page.getViewport({ scale: 1.0 });
        const context = canvas.getContext('2d');
        if (!context) return;

        canvas.width = viewport.width;
        canvas.height = viewport.height;

        const renderContext = {
          canvasContext: context,
          viewport: viewport
        };

        if (this.renderTask) {
          try { this.renderTask.cancel(); } catch (e) {}
        }

        const renderTask = page.render(renderContext);
        this.renderTask = renderTask;

        try {
          await renderTask.promise;
        } catch (err) {
          if (err && err.name !== 'RenderingCancelledException') throw err;
        } finally {
          if (this.renderTask === renderTask) {
            this.renderTask = null;
          }
        }
      } catch (err) {
        if (loadId === this.currentLoadId && err?.name !== 'RenderingCancelledException') {
          console.error("PDF canvas ingestion matrices skipped", err);
        }
      }
    },

    // Handle clicks over matrix overlay
    handleMatrixOverlayClick(e) {
      if (!this.activeFieldToMap) return;

      const rect = e.currentTarget.getBoundingClientRect();
      const clickX = e.clientX - rect.left;
      const clickY = e.clientY - rect.top;

      const xPct = (clickX / rect.width) * 100;
      const yPct = (clickY / rect.height) * 100;

      this.updateCoordinates(this.activeTemplateId, this.activeFieldToMap, xPct, yPct);
      this.activeFieldToMap = null;
    },

    updateCoordinates(templateId, fieldId, xPct, yPct) {
      this.templates = this.templates.map(tpl => {
        if (tpl.template_id === templateId) {
          return {
            ...tpl,
            schema_json: {
              ...tpl.schema_json,
              fields_mapping: tpl.schema_json.fields_mapping.map(field =>
                field.field_id === fieldId
                  ? { ...field, x_percentage: parseFloat(xPct.toFixed(2)), y_percentage: parseFloat(yPct.toFixed(2)) }
                  : field
              )
            }
          };
        }
        return tpl;
      });
    },

    // CRUD - Tenant
    async handleAddTenant() {
      if (!this.newTenant.tenant_id || !this.newTenant.corporate_name) return;
      try {
        const res = await fetch('/api/v1/tenants', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(this.newTenant)
        });
        if (res.ok) {
          await this.syncDatabaseStates();
          this.newTenant = { tenant_id: '', corporate_name: '', tenant_scope: '' };
          this.showTenantModal = false;
        }
      } catch (err) {
        console.error(err);
      }
    },

    // CRUD - Category
    async handleAddCategory() {
      if (!this.newCategory.category_id || !this.newCategory.name) return;
      try {
        const res = await fetch('/api/v1/categories', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...this.newCategory, tenant_id: this.activeTenant })
        });
        if (res.ok) {
          await this.syncDatabaseStates();
          this.newCategory = { category_id: '', name: '', description: '' };
          this.showCategoryModal = false;
        }
      } catch (err) {
        console.error(err);
      }
    },

    async handleDeleteCategory(id) {
      try {
        const res = await fetch(`/api/v1/categories/${id}`, { method: 'DELETE' });
        if (res.ok) {
          await this.syncDatabaseStates();
        }
      } catch (err) {
        console.error(err);
      }
    },

    // CRUD - Template
    async handleAddTemplate() {
      if (!this.newTemplate.template_id || !this.newTemplate.name) return;
      const payload = {
        template_id: this.newTemplate.template_id,
        tenant_id: this.activeTenant,
        name: this.newTemplate.name,
        schema_json: {
          fields_mapping: [
            { field_id: "corporate_id", label: "Corporate Entity ID (Regulated)", type: "alphanumeric", page_index: 0, x_percentage: 14.50, y_percentage: 22.85 },
            { field_id: "registered_trade_name_ar", label: "Registered Trade Name (Arabic)", type: "arabic", page_index: 0, x_percentage: 14.50, y_percentage: 30.15 },
            { field_id: "operational_capital_usd", label: "Operational Equity (USD)", type: "numeric", page_index: 0, x_percentage: 14.50, y_percentage: 37.45 },
            { field_id: "incorporation_date", label: "Date of Incorporation", type: "date", page_index: 0, x_percentage: 55.20, y_percentage: 37.45 }
          ]
        }
      };

      try {
        const res = await fetch('/api/v1/templates', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        if (res.ok) {
          await this.syncDatabaseStates();
          this.activeTemplateId = this.newTemplate.template_id;
          this.newTemplate = { template_id: '', name: '' };
          this.showTemplateModal = false;
          this.activeView = 'sandbox'; // redirect to sandbox to map template
        }
      } catch (err) {
        console.error(err);
      }
    },

    async handleDeleteTemplate(id) {
      try {
        const res = await fetch(`/api/v1/templates/${id}`, { method: 'DELETE' });
        if (res.ok) {
          await this.syncDatabaseStates();
          if (this.activeTemplateId === id) {
            this.activeTemplateId = this.templates[0]?.template_id || 'g12';
          }
        }
      } catch (err) {
        console.error(err);
      }
    },

    async handleSaveCoordinates(templateId) {
      const active = this.templates.find(t => t.template_id === templateId);
      if (!active) return;
      try {
        const res = await fetch('/api/v1/templates', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(active)
        });
        if (res.ok) {
          await this.syncDatabaseStates();
          alert('Template mapping vectors persisted to database.');
        }
      } catch (err) {
        console.error(err);
      }
    },

    exportTemplateJSON(tpl) {
      const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(tpl, null, 2));
      const dlAnchorElem = document.createElement('a');
      dlAnchorElem.setAttribute('href', dataStr);
      dlAnchorElem.setAttribute('download', `schema_${tpl.template_id}.json`);
      dlAnchorElem.click();
    },

    // Compiler Action
    async handleRunCompiler() {
      this.compiling = true;
      this.downloadUrl = '';
      try {
        const payload = {
          template_id: this.activeTemplateId,
          tenant_id: this.activeTenant,
          form_values: this.formInputs,
          source_path: this.uploadedRefPath || null
        };

        const res = await fetch('/api/v1/document/compile', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });

        if (res.ok) {
          const data = await res.json();
          this.downloadUrl = data.download_url;
          this.viewerTab = 'preview';
          await this.syncDatabaseStates();
        } else {
          const errData = await res.json();
          alert(`Compile error: ${errData.error || 'Coordinates compile failure.'}`);
        }
      } catch (err) {
        console.error(err);
      } finally {
        this.compiling = false;
      }
    },

    // File Upload Handler
    async uploadFile(file) {
      if (!file) return;
      if (file.type !== 'application/pdf') {
        this.uploadStatus = 'failed';
        this.errorMessage = 'MIME restriction: Selected upload must be a valid PDF format.';
        return;
      }

      this.uploadStatus = 'uploading';
      this.uploadProgress = 20;

      try {
        this.uploadProgress = 50;
        const res = await fetch('/api/v1/document/upload', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/pdf',
            'tenant-id': this.activeTenant
          },
          body: file
        });

        this.uploadProgress = 80;
        if (res.ok) {
          const data = await res.json();
          this.uploadedRefPath = data.path;
          this.uploadedFilename = data.filename || file.name;
          this.uploadedSize = file.size;
          this.uploadStatus = 'success';
          this.uploadProgress = 100;
          await this.syncDatabaseStates();
        } else {
          const errData = await res.json();
          throw new Error(errData.error || 'Upload error');
        }
      } catch (err) {
        this.uploadStatus = 'failed';
        this.errorMessage = err.message || 'Pipeline file upload aborted.';
      }
    },

    unloadUploadedPdf() {
      this.uploadStatus = 'idle';
      this.uploadedRefPath = '';
      this.uploadedFilename = '';
      this.uploadedSize = 0;
      this.downloadUrl = '';
      this.viewerTab = 'mapper';
    },

    formatDate(isoString) {
      if (!isoString) return '';
      const d = new Date(isoString);
      if (isNaN(d.getTime())) return isoString;
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' ' + d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
    },

    formatSize(bytes) {
      if (bytes === 0) return '0 Bytes';
      const k = 1024;
      const sizes = ['Bytes', 'KB', 'MB'];
      const i = Math.floor(Math.log(bytes) / Math.log(k));
      return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }
  }));
});
