import { useEffect, useState } from 'react'
import './App.css'

async function apiRequest(path, { method = 'GET', body } = {}) {
  const headers = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (method !== 'GET') {
    const csrfResponse = await fetch('/api/auth/csrf/', { credentials: 'include' })
    const csrfData = await csrfResponse.json()
    if (!csrfResponse.ok) {
      throw new Error(csrfData.detail || 'Could not prepare a secure request.')
    }
    headers['X-CSRFToken'] = csrfData.csrfToken
  }

  const response = await fetch(path, {
    method,
    credentials: 'include',
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const data = await response.json()
  if (!response.ok) throw new Error(data.detail || 'The request failed.')
  return data
}

function LoginScreen({
  username,
  setUsername,
  password,
  setPassword,
  error,
  isSubmitting,
  onSubmit,
}) {
  return (
    <main className="auth-page">
      <form className="auth-card" onSubmit={onSubmit}>
        <h1>Wellnest</h1>
        <p>Sign in to your pharmacy inventory</p>
        <label>
          Username
          <input
            type="text"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="username"
            required
          />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        {error && <p className="auth-error" role="alert">{error}</p>}
        <button type="submit" disabled={isSubmitting}>
          {isSubmitting ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </main>
  )
}

const emptyBatch = {
  sku: '',
  name: '',
  category: '',
  batch: '',
  quantity: '',
  reorderLevel: '',
  expiry: '',
  supplier: '',
  reference: '',
  purchaseCost: '',
  sellingPrice: '',
  witnessId: '',
}

const emptyDispense = {
  sku: '',
  transactionType: 'Sale',
  quantity: '',
  recipient: '',
  reference: '',
  amountReceived: '',
  paymentMethod: '',
}

const emptyStockCount = {
  batch: '',
  quantity: '',
  reason: '',
  reference: '',
  witnessId: '',
}

const emptySupplierInvoice = {
  supplier: '',
  invoiceNumber: '',
  invoiceAmount: '',
  amountPaid: '0',
  dueDate: '',
  purchaseOrderId: '',
}

const emptySupplierPayment = {
  invoiceId: '',
  amount: '',
  method: '',
  reference: '',
}

const emptyCustomerPayment = {
  saleId: '',
  amount: '',
  method: '',
  reference: '',
}

const emptyPrescription = {
  reference: '',
  patientReference: '',
  prescriberName: '',
  prescriberRegistration: '',
  issuedDate: '',
  expiresDate: '',
  sku: '',
  quantity: '',
  directions: '',
}

const emptyPrescriptionDispense = {
  lineKey: '',
  quantity: '',
  amountReceived: '0',
  paymentMethod: '',
  reference: '',
  witnessId: '',
}

const emptyPurchaseOrder = {
  number: '',
  supplierId: '',
  expectedDate: '',
  sku: '',
  quantity: '',
  unitCost: '',
}

const emptyPurchaseReceipt = {
  orderId: '',
  lineId: '',
  quantity: '',
  batch: '',
  expiry: '',
  sellingPrice: '',
  witnessId: '',
}

const emptyTransfer = {
  destinationBranchId: '',
  reference: '',
  sku: '',
  quantity: '',
  witnessId: '',
}

const emptyProduct = {
  sku: '',
  name: '',
  category: '',
  unit: 'unit',
  barcode: '',
  requiresPrescription: false,
  isControlled: false,
  controlledSchedule: '',
}

const emptyBarcodeAlias = { sku: '', value: '', symbology: '' }
const emptySupplier = { name: '', contactName: '', email: '', phone: '', address: '' }
const emptySupplierProduct = {
  sku: '',
  supplierId: '',
  supplierSku: '',
  unitCost: '',
  leadTimeDays: '0',
  isPreferred: true,
}

function getStockStatus(medicine, today = new Date()) {
  const expiryDate = new Date(`${medicine.expiry}T00:00:00`)

  if (expiryDate < today) return 'Expired'
  if (medicine.quantity === 0) return 'Out of stock'
  if (medicine.quantity <= medicine.reorderLevel) return 'Low stock'
  return 'In stock'
}


function getSupplierInvoiceStatus(invoice) {
  const balance = invoice.invoiceAmount - invoice.amountPaid
  const today = new Date().toISOString().slice(0, 10)

  if (balance <= 0) return 'Paid'
  if (invoice.dueDate && invoice.dueDate < today) return 'Overdue'
  if (invoice.amountPaid > 0) return 'Partially paid'
  return 'Unpaid'
}

function getSalePaymentStatus(sale) {
  if (sale.balanceDue <= 0) return 'Paid'
  if (sale.amountReceived > 0) return 'Partially paid'
  return 'Unpaid'
}

function App() {
  const [activePage, setActivePage] = useState('Overview')
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [inventory, setInventory] = useState([])
  const [showAddForm, setShowAddForm] = useState(false)
  const [newBatch, setNewBatch] = useState(emptyBatch)
  const [formError, setFormError] = useState('')
  const [stockMovements, setStockMovements] = useState([])
  const [showDispenseForm, setShowDispenseForm] = useState(false)
  const [dispenseForm, setDispenseForm] = useState(emptyDispense)
  const [dispenseError, setDispenseError] = useState('')
  const [showStockCountForm, setShowStockCountForm] = useState(false)
  const [stockCountForm, setStockCountForm] = useState(emptyStockCount)
  const [stockCountError, setStockCountError] = useState('')
  const [sales, setSales] = useState([])
  const [supplierInvoices, setSupplierInvoices] = useState([])
  const [supplierPayments, setSupplierPayments] = useState([])
  const [showSupplierInvoiceForm, setShowSupplierInvoiceForm] = useState(false)
  const [supplierInvoiceForm, setSupplierInvoiceForm] = useState(emptySupplierInvoice)
  const [supplierInvoiceError, setSupplierInvoiceError] = useState('')
  const [showSupplierPaymentForm, setShowSupplierPaymentForm] = useState(false)
  const [supplierPaymentForm, setSupplierPaymentForm] = useState(emptySupplierPayment)
  const [supplierPaymentError, setSupplierPaymentError] = useState('')
  const [customerPayments, setCustomerPayments] = useState([])
  const [showCustomerPaymentForm, setShowCustomerPaymentForm] = useState(false)
  const [customerPaymentForm, setCustomerPaymentForm] = useState(emptyCustomerPayment)
  const [customerPaymentError, setCustomerPaymentError] = useState('')
  const [currentUser, setCurrentUser] = useState(null)
  const [authLoading, setAuthLoading] = useState(true)
  const [authError, setAuthError] = useState('')
  const [loginUsername, setLoginUsername] = useState('')
  const [loginPassword, setLoginPassword] = useState('')
  const [loginSubmitting, setLoginSubmitting] = useState(false)
  const [branches, setBranches] = useState([])
  const [activeBranchId, setActiveBranchId] = useState('')
  const [loadedBranchId, setLoadedBranchId] = useState('')
  const [dataError, setDataError] = useState('')
  const [products, setProducts] = useState([])
  const [suppliers, setSuppliers] = useState([])
  const [branchStaff, setBranchStaff] = useState([])
  const [prescriptions, setPrescriptions] = useState([])
  const [purchaseOrders, setPurchaseOrders] = useState([])
  const [reorderSuggestions, setReorderSuggestions] = useState([])
  const [transfers, setTransfers] = useState([])
  const [analytics, setAnalytics] = useState(null)
  const [workflowError, setWorkflowError] = useState('')
  const [barcodeInput, setBarcodeInput] = useState('')
  const [prescriptionForm, setPrescriptionForm] = useState(emptyPrescription)
  const [prescriptionDispenseForm, setPrescriptionDispenseForm] = useState(emptyPrescriptionDispense)
  const [purchaseOrderForm, setPurchaseOrderForm] = useState(emptyPurchaseOrder)
  const [purchaseReceiptForm, setPurchaseReceiptForm] = useState(emptyPurchaseReceipt)
  const [transferForm, setTransferForm] = useState(emptyTransfer)
  const [transferBatch, setTransferBatch] = useState('')
  const [transferWitnessId, setTransferWitnessId] = useState('')
  const [productForm, setProductForm] = useState(emptyProduct)
  const [barcodeAliasForm, setBarcodeAliasForm] = useState(emptyBarcodeAlias)
  const [supplierForm, setSupplierForm] = useState(emptySupplier)
  const [supplierProductForm, setSupplierProductForm] = useState(emptySupplierProduct)
  const [reportStart, setReportStart] = useState(() => {
    const start = new Date()
    start.setDate(start.getDate() - 30)
    return start.toISOString().slice(0, 10)
  })
  const [reportEnd, setReportEnd] = useState(() => new Date().toISOString().slice(0, 10))
  const [today] = useState(() => {
    const currentDate = new Date()
    currentDate.setHours(0, 0, 0, 0)
    return currentDate
  })

  useEffect(() => {
    if (!currentUser) return
    let cancelled = false

    apiRequest('/api/branches/')
      .then(({ branches: availableBranches }) => {
        if (cancelled) return
        setBranches(availableBranches)
        setActiveBranchId((current) => {
          if (availableBranches.some((branch) => String(branch.id) === String(current))) {
            return String(current)
          }
          const membershipBranch = currentUser.memberships.find((membership) =>
            availableBranches.some((branch) => branch.id === membership.branchId)
          )?.branchId
          return String(membershipBranch ?? availableBranches[0]?.id ?? '')
        })
      })
      .catch((error) => {
        if (!cancelled) setDataError(error.message || 'Could not load your branches.')
      })

    return () => {
      cancelled = true
    }
  }, [currentUser])

  useEffect(() => {
    if (!currentUser || !activeBranchId) return
    let cancelled = false

    refreshBranchData(activeBranchId, () => !cancelled)
      .then(() => {
        if (!cancelled) {
        setDataError('')
        setLoadedBranchId(activeBranchId)
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setDataError(error.message || 'Could not load branch data.')
          setLoadedBranchId(activeBranchId)
        }
      })

    return () => {
      cancelled = true
    }
  }, [currentUser, activeBranchId])

  async function saveBranchAction(path, values) {
    await apiRequest(path, {
      method: 'POST',
      body: { ...values, branchId: Number(activeBranchId) },
    })
    await refreshBranchData(activeBranchId)
  }

  async function refreshBranchData(branchId = activeBranchId, isCurrent = () => true) {
    if (!branchId) return
    const query = `?branchId=${encodeURIComponent(branchId)}`
    const [data, productData, supplierData, staffData, prescriptionData, orderData, transferData, reorderData] =
      await Promise.all([
        apiRequest(`/api/data/${query}`),
        apiRequest('/api/products/'),
        apiRequest('/api/suppliers/'),
        apiRequest(`/api/branch-staff/${query}`),
        apiRequest(`/api/prescriptions/${query}`),
        apiRequest(`/api/purchase-orders/${query}`),
        apiRequest(`/api/transfers/${query}`),
        apiRequest(`/api/reorder-suggestions/${query}`),
      ])
    if (isCurrent()) {
      setInventory(data.inventory)
      setStockMovements(data.stockMovements)
      setSales(data.sales)
      setSupplierInvoices(data.supplierInvoices)
      setSupplierPayments(data.supplierPayments)
      setCustomerPayments(data.customerPayments)
      setProducts(productData.products)
      setSuppliers(supplierData.suppliers)
      setBranchStaff(staffData.members)
      setPrescriptions(prescriptionData.prescriptions)
      setPurchaseOrders(orderData.purchaseOrders)
      setTransfers(transferData.transfers)
      setReorderSuggestions(reorderData.suggestions)
    }
  }

  useEffect(() => {
    if (activePage !== 'Reports' || !activeBranchId) return
    let cancelled = false
    const params = new URLSearchParams({
      branchId: activeBranchId,
      start: reportStart,
      end: reportEnd,
    })
    apiRequest(`/api/reports/analytics/?${params}`)
      .then((data) => {
        if (!cancelled) {
          setAnalytics(data)
          setWorkflowError('')
        }
      })
      .catch((error) => {
        if (!cancelled) setWorkflowError(error.message || 'Could not load analytics.')
      })
    return () => {
      cancelled = true
    }
  }, [activePage, activeBranchId, reportStart, reportEnd])

  useEffect(() => {
    let cancelled = false

    async function restoreSession() {
      try {
        const response = await fetch('/api/auth/me/', {
          credentials: 'include',
        })

        if (response.status === 401) return

        const data = await response.json()
        if (!response.ok) {
          throw new Error(data.detail || 'Could not check your sign-in.')
        }

        if (!cancelled) setCurrentUser(data.user)
      } catch {
        if (!cancelled) {
          setAuthError('Could not reach the server. Check that Django is running.')
        }
      } finally {
        if (!cancelled) setAuthLoading(false)
      }
    }

    restoreSession()
    return () => {
      cancelled = true
    }
  }, [])

  async function handleLogin(event) {
    event.preventDefault()
    setAuthError('')
    setLoginSubmitting(true)

    try {
      const csrfResponse = await fetch('/api/auth/csrf/', {
        credentials: 'include',
      })
      const csrfData = await csrfResponse.json()

      if (!csrfResponse.ok) {
        throw new Error(csrfData.detail || 'Could not prepare secure sign-in.')
      }

      const response = await fetch('/api/auth/login/', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfData.csrfToken,
        },
        body: JSON.stringify({
          username: loginUsername,
          password: loginPassword,
        }),
      })
      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.detail || 'Sign-in failed.')
      }

      setCurrentUser(data.user)
      setLoginPassword('')
    } catch (error) {
      setAuthError(error.message || 'Sign-in failed. Please try again.')
    } finally {
      setLoginSubmitting(false)
    }
  }

  async function handleLogout() {
    setAuthError('')

    try {
      const csrfResponse = await fetch('/api/auth/csrf/', {
        credentials: 'include',
      })
      const csrfData = await csrfResponse.json()

      const response = await fetch('/api/auth/logout/', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'X-CSRFToken': csrfData.csrfToken,
        },
      })
      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.detail || 'Sign-out failed.')
      }

      window.location.reload()
    } catch (error) {
      setAuthError(error.message || 'Sign-out failed. Please try again.')
    }
  }

  const totalProducts = new Set(
    inventory.map((medicine) => medicine.sku)
  ).size

  const lowStockCount = inventory.filter(
    (medicine) => getStockStatus(medicine, today) === 'Low stock'
  ).length

  const outOfStockCount = inventory.filter(
    (medicine) => getStockStatus(medicine, today) === 'Out of stock'
  ).length

  const expiredCount = inventory.filter(
    (medicine) =>
      medicine.quantity > 0 && getStockStatus(medicine, today) === 'Expired'
  ).length

  const expiringSoonCount = inventory.filter((medicine) => {
    const expiryDate = new Date(`${medicine.expiry}T00:00:00`)
    const daysUntilExpiry = Math.ceil(
      (expiryDate - today) / (1000 * 60 * 60 * 24)
    )

    return (
      medicine.quantity > 0 &&
      daysUntilExpiry >= 0 &&
      daysUntilExpiry <= 90
    )
  }).length

  const filteredMedicines = inventory.filter((medicine) => {
    const searchableText =
      `${medicine.name} ${medicine.category} ${medicine.sku} ${medicine.batch}`.toLowerCase()

    const matchesSearch = searchableText.includes(
      searchTerm.trim().toLowerCase()
    )
    const matchesStatus =
      statusFilter === 'all' || getStockStatus(medicine, today) === statusFilter

    return matchesSearch && matchesStatus
  })

  const selectedPrescriptionOption = prescriptionDispenseForm.lineKey
    .split(':')
  const selectedPrescription = prescriptions.find(
    (item) => String(item.id) === selectedPrescriptionOption[0],
  )
  const selectedPrescriptionLine = selectedPrescription?.lines.find(
    (item) => String(item.id) === selectedPrescriptionOption[1],
  )
  const selectedBatchProduct = products.find((item) => item.sku === newBatch.sku)
  const selectedCountBatch = inventory.find((item) => item.batch === stockCountForm.batch)
  const selectedReceiptOrder = purchaseOrders.find(
    (item) => String(item.id) === purchaseReceiptForm.orderId,
  )
  const selectedReceiptLine = selectedReceiptOrder?.lines.find(
    (item) => String(item.id) === purchaseReceiptForm.lineId,
  )
  const selectedTransferProduct = products.find((item) => item.sku === transferForm.sku)
  const canManageBranch =
    currentUser?.isSuperuser ||
    currentUser?.memberships.some(
      (membership) =>
        String(membership.branchId) === String(activeBranchId) &&
        membership.role === 'branch_manager',
    )

  function handleFormChange(event) {
    const { name, value } = event.target
    setNewBatch((current) => ({ ...current, [name]: value }))
  }

  function handleDispenseFormChange(event) {
    const { name, value } = event.target
    setDispenseForm((current) => ({ ...current, [name]: value }))
  }

  function handleStockCountFormChange(event) {
    const { name, value } = event.target
    setStockCountForm((current) => ({ ...current, [name]: value }))
  }

  async function handleAddBatch(event) {
    event.preventDefault()

    const batchNumber = newBatch.batch.trim()

    if (
      inventory.some(
        (item) => item.batch.toLowerCase() === batchNumber.toLowerCase()
      )
    ) {
      setFormError('That batch number is already in the inventory.')
      return
    }

    const quantity = Number(newBatch.quantity)
    const reorderLevel = Number(newBatch.reorderLevel)
    const purchaseCost = Number(newBatch.purchaseCost)
    const sellingPrice = Number(newBatch.sellingPrice)
    const sku = newBatch.sku.trim()
    const name = newBatch.name.trim()
    const supplier = newBatch.supplier.trim()
    const reference = newBatch.reference.trim()

    try {
      await saveBranchAction('/api/batches/', {
        sku,
        name,
        category: newBatch.category.trim(),
        batch: batchNumber,
        quantity,
        reorderLevel,
        expiry: newBatch.expiry,
        supplier,
        reference,
        purchaseCost,
        sellingPrice,
        witnessId: newBatch.witnessId || null,
      })
      setNewBatch(emptyBatch)
      setFormError('')
      setShowAddForm(false)
    } catch (error) {
      setFormError(error.message || 'Could not save this batch.')
    }
  }

  async function handleDispense(event) {
    event.preventDefault()

    const quantity = Number(dispenseForm.quantity)
    const transactionType = dispenseForm.transactionType
    const amountReceived = Number(dispenseForm.amountReceived)
    const paymentMethod = dispenseForm.paymentMethod
    const recipient = dispenseForm.recipient.trim()
    const reference = dispenseForm.reference.trim()

    if (!recipient || !reference || !Number.isInteger(quantity) || quantity <= 0) {
      setDispenseError('Enter a valid quantity, recipient, and reference.')
      return
    }

    const dispenseDate = new Date()
    dispenseDate.setHours(0, 0, 0, 0)

    const eligibleBatches = inventory
      .filter(
        (item) =>
          item.sku === dispenseForm.sku &&
          item.quantity > 0 &&
          new Date(`${item.expiry}T00:00:00`) >= dispenseDate
      )
      .sort((first, second) => first.expiry.localeCompare(second.expiry))

    const availableQuantity = eligibleBatches.reduce(
      (total, item) => total + item.quantity,
      0
    )

    if (quantity > availableQuantity) {
      setDispenseError(
        `Only ${availableQuantity} units are available in non-expired batches.`
      )
      return
    }

    let remaining = quantity
    const allocations = []

    for (const item of eligibleBatches) {
      if (remaining === 0) break

      const quantityFromBatch = Math.min(item.quantity, remaining)
      allocations.push({ batch: item, quantity: quantityFromBatch })
      remaining -= quantityFromBatch
    }

    const saleAmount =
      transactionType === 'Sale'
        ? allocations.reduce(
            (total, allocation) =>
              total +
              allocation.quantity * Number(allocation.batch.sellingPrice || 0),
            0
          )
        : 0

    if (
      transactionType === 'Sale' &&
      (!paymentMethod ||
        !Number.isFinite(amountReceived) ||
        amountReceived < 0 ||
        amountReceived > saleAmount)
    ) {
      setDispenseError(
        `Enter a payment method and an amount received from 0 to ${saleAmount}.`
      )
      return
    }

    try {
      await saveBranchAction('/api/dispense/', {
        sku: dispenseForm.sku,
        transactionType,
        quantity,
        recipient,
        reference,
        amountReceived,
        paymentMethod,
      })
      setDispenseForm(emptyDispense)
      setDispenseError('')
      setShowDispenseForm(false)
    } catch (error) {
      setDispenseError(error.message || 'Could not record this dispensing.')
    }
  }



  function handleSupplierInvoiceChange(event) {
    const { name, value } = event.target
    setSupplierInvoiceForm((current) => ({ ...current, [name]: value }))
  }

  function handleSupplierPaymentChange(event) {
    const { name, value } = event.target
    setSupplierPaymentForm((current) => ({ ...current, [name]: value }))
  }

  async function handleSaveSupplierInvoice(event) {
    event.preventDefault()

    const supplier = supplierInvoiceForm.supplier.trim()
    const invoiceNumber = supplierInvoiceForm.invoiceNumber.trim()
    const invoiceAmount = Number(supplierInvoiceForm.invoiceAmount)
    const amountPaid = Number(supplierInvoiceForm.amountPaid)

    if (
      !supplier ||
      !invoiceNumber ||
      !supplierInvoiceForm.dueDate ||
      !Number.isFinite(invoiceAmount) ||
      invoiceAmount <= 0 ||
      !Number.isFinite(amountPaid) ||
      amountPaid < 0 ||
      amountPaid > invoiceAmount
    ) {
      setSupplierInvoiceError('Enter invoice details and valid amounts. Amount paid cannot exceed the invoice total.')
      return
    }

    if (supplierInvoices.some((invoice) => invoice.invoiceNumber.toLowerCase() === invoiceNumber.toLowerCase())) {
      setSupplierInvoiceError('That invoice number has already been entered.')
      return
    }

    try {
      await saveBranchAction('/api/supplier-invoices/', {
        supplier,
        invoiceNumber,
        invoiceAmount,
        amountPaid,
        dueDate: supplierInvoiceForm.dueDate,
        purchaseOrderId: supplierInvoiceForm.purchaseOrderId || null,
        method: 'Opening payment',
      })
      setSupplierInvoiceForm(emptySupplierInvoice)
      setSupplierInvoiceError('')
      setShowSupplierInvoiceForm(false)
    } catch (error) {
      setSupplierInvoiceError(error.message || 'Could not save the supplier invoice.')
    }
  }

  async function handleRecordSupplierPayment(event) {
    event.preventDefault()

    const amount = Number(supplierPaymentForm.amount)
    const reference = supplierPaymentForm.reference.trim()
    const invoice = supplierInvoices.find((item) => item.id === supplierPaymentForm.invoiceId)

    if (!invoice || !supplierPaymentForm.method || !reference || !Number.isFinite(amount) || amount <= 0) {
      setSupplierPaymentError('Select an invoice and enter a valid payment, method, and reference.')
      return
    }

    const balance = invoice.invoiceAmount - invoice.amountPaid
    if (amount > balance) {
      setSupplierPaymentError(`Payment cannot exceed the remaining balance of ${balance.toLocaleString()}.`)
      return
    }

    try {
      await saveBranchAction(`/api/supplier-invoices/${invoice.id}/payments/`, {
        amount,
        method: supplierPaymentForm.method,
        reference,
      })
      setSupplierPaymentForm(emptySupplierPayment)
      setSupplierPaymentError('')
      setShowSupplierPaymentForm(false)
    } catch (error) {
      setSupplierPaymentError(error.message || 'Could not record the supplier payment.')
    }
  }

  function handleCustomerPaymentChange(event) {
    const { name, value } = event.target
    setCustomerPaymentForm((current) => ({ ...current, [name]: value }))
  }

  async function handleRecordCustomerPayment(event) {
    event.preventDefault()

    const sale = sales.find((item) => item.id === customerPaymentForm.saleId)
    const amount = Number(customerPaymentForm.amount)
    const method = customerPaymentForm.method
    const reference = customerPaymentForm.reference.trim()

    if (!sale || !method || !reference || !Number.isFinite(amount) || amount <= 0) {
      setCustomerPaymentError('Select an outstanding sale and enter a valid payment, method, and reference.')
      return
    }

    if (amount > sale.balanceDue) {
      setCustomerPaymentError(`Payment cannot exceed the outstanding balance of ${sale.balanceDue.toLocaleString()}.`)
      return
    }

    try {
      await saveBranchAction(`/api/sales/${sale.id}/payments/`, {
        amount,
        method,
        reference,
      })
      setCustomerPaymentForm(emptyCustomerPayment)
      setCustomerPaymentError('')
      setShowCustomerPaymentForm(false)
    } catch (error) {
      setCustomerPaymentError(error.message || 'Could not record the customer payment.')
    }
  }

  async function handleStockCount(event) {
    event.preventDefault()

    const countedQuantity = Number(stockCountForm.quantity)
    const reference = stockCountForm.reference.trim()
    const reason = stockCountForm.reason

    if (
      !stockCountForm.batch ||
      !Number.isInteger(countedQuantity) ||
      countedQuantity < 0 ||
      !reason ||
      !reference
    ) {
      setStockCountError(
        'Select a batch, enter a whole-number count of zero or more, and provide a reason and reference.'
      )
      return
    }

    const countedBatch = inventory.find(
      (item) => item.batch === stockCountForm.batch
    )

    if (!countedBatch) {
      setStockCountError('The selected batch could not be found.')
      return
    }

    const difference = countedQuantity - countedBatch.quantity

    if (difference === 0) {
      setStockCountError(
        'The counted quantity matches the recorded quantity. No adjustment is needed.'
      )
      return
    }

    try {
      await saveBranchAction('/api/stock-count/', {
        batch: countedBatch.batch,
        quantity: countedQuantity,
        reason,
        reference,
        witnessId: stockCountForm.witnessId || null,
      })
      setStockCountForm(emptyStockCount)
      setStockCountError('')
      setShowStockCountForm(false)
    } catch (error) {
      setStockCountError(error.message || 'Could not save the stock count.')
    }
  }

  async function handleBarcodeLookup(event) {
    event.preventDefault()
    setWorkflowError('')
    try {
      const { product } = await apiRequest(
        `/api/barcode/lookup/?value=${encodeURIComponent(barcodeInput.trim())}`,
      )
      setSearchTerm(product.name)
      if (product.isControlled || product.requiresPrescription) {
        setWorkflowError(
          `${product.name} requires the prescription workflow${product.isControlled ? ' and controlled-medicine witness' : ''}.`,
        )
      }
      setBarcodeInput('')
    } catch (error) {
      setWorkflowError(error.message || 'Barcode lookup failed.')
    }
  }

  async function handleCreatePrescription(event) {
    event.preventDefault()
    setWorkflowError('')
    try {
      await saveBranchAction('/api/prescriptions/create/', {
        ...prescriptionForm,
        branchId: Number(activeBranchId),
        lines: [{
          sku: prescriptionForm.sku,
          quantity: Number(prescriptionForm.quantity),
          directions: prescriptionForm.directions,
        }],
      })
      setPrescriptionForm(emptyPrescription)
    } catch (error) {
      setWorkflowError(error.message || 'Could not save the prescription.')
    }
  }

  async function handleVerifyPrescription(prescriptionId) {
    setWorkflowError('')
    try {
      await saveBranchAction(`/api/prescriptions/${prescriptionId}/verify/`, {})
    } catch (error) {
      setWorkflowError(error.message || 'Could not verify prescription.')
    }
  }

  async function handlePrescriptionDispense(event) {
    event.preventDefault()
    const [prescriptionId, lineId] = prescriptionDispenseForm.lineKey.split(':')
    const prescription = prescriptions.find((item) => String(item.id) === prescriptionId)
    if (!prescription || !lineId) {
      setWorkflowError('Select a verified prescription item to dispense.')
      return
    }
    const line = prescription.lines.find((item) => String(item.id) === lineId)
    setWorkflowError('')
    try {
      await saveBranchAction(`/api/prescriptions/${prescription.id}/dispense/`, {
        branchId: Number(activeBranchId),
        lineId: Number(lineId),
        quantity: Number(prescriptionDispenseForm.quantity),
        amountReceived: Number(prescriptionDispenseForm.amountReceived),
        paymentMethod: prescriptionDispenseForm.paymentMethod,
        reference: prescriptionDispenseForm.reference,
        patientReference: prescription.patientReference,
        witnessId: prescriptionDispenseForm.witnessId || null,
      })
      setPrescriptionDispenseForm(emptyPrescriptionDispense)
    } catch (error) {
      setWorkflowError(error.message || `Could not dispense ${line?.name || 'prescription item'}.`)
    }
  }

  async function handleCreatePurchaseOrder(event) {
    event.preventDefault()
    setWorkflowError('')
    try {
      await saveBranchAction('/api/purchase-orders/create/', {
        ...purchaseOrderForm,
        supplierId: Number(purchaseOrderForm.supplierId),
        branchId: Number(activeBranchId),
        lines: [{
          sku: purchaseOrderForm.sku,
          quantity: Number(purchaseOrderForm.quantity),
          unitCost: Number(purchaseOrderForm.unitCost),
        }],
      })
      setPurchaseOrderForm(emptyPurchaseOrder)
    } catch (error) {
      setWorkflowError(error.message || 'Could not create purchase order.')
    }
  }

  async function handleCreateReorderDraft(sku) {
    setWorkflowError('')
    try {
      await saveBranchAction('/api/purchase-orders/reorder-draft/', {
        branchId: Number(activeBranchId),
        sku,
      })
    } catch (error) {
      setWorkflowError(error.message || 'Could not create a reorder draft.')
    }
  }

  async function handleSubmitPurchaseOrder(orderId) {
    setWorkflowError('')
    try {
      await saveBranchAction(`/api/purchase-orders/${orderId}/submit/`, {
        branchId: Number(activeBranchId),
      })
    } catch (error) {
      setWorkflowError(error.message || 'Could not submit purchase order.')
    }
  }

  async function handleReceivePurchaseOrder(event) {
    event.preventDefault()
    setWorkflowError('')
    try {
      await saveBranchAction(`/api/purchase-orders/${purchaseReceiptForm.orderId}/receive/`, {
        branchId: Number(activeBranchId),
        receipts: [{
          lineId: Number(purchaseReceiptForm.lineId),
          quantity: Number(purchaseReceiptForm.quantity),
          batch: purchaseReceiptForm.batch,
          expiry: purchaseReceiptForm.expiry,
          sellingPrice: Number(purchaseReceiptForm.sellingPrice),
          witnessId: purchaseReceiptForm.witnessId || null,
        }],
      })
      setPurchaseReceiptForm(emptyPurchaseReceipt)
    } catch (error) {
      setWorkflowError(error.message || 'Could not receive purchase order.')
    }
  }

  async function handleCreateTransfer(event) {
    event.preventDefault()
    setWorkflowError('')
    try {
      await saveBranchAction('/api/transfers/create/', {
        sourceBranchId: Number(activeBranchId),
        destinationBranchId: Number(transferForm.destinationBranchId),
        reference: transferForm.reference,
        lines: [{
          sku: transferForm.sku,
          quantity: Number(transferForm.quantity),
        }],
        witnessId: transferForm.witnessId || null,
      })
      setTransferWitnessId(transferForm.witnessId)
      setTransferForm(emptyTransfer)
    } catch (error) {
      setWorkflowError(error.message || 'Could not request branch transfer.')
    }
  }

  async function handleTransferAction(transferId, action, branchId = activeBranchId) {
    setWorkflowError('')
    try {
      await saveBranchAction(`/api/transfers/${transferId}/${action}/`, {
        branchId: Number(branchId),
        witnessId: transferWitnessId || null,
        ...(action === 'receive' && transferBatch
          ? { batches: { [String(transfers.find((item) => item.id === transferId)?.lines[0]?.id)]: transferBatch } }
          : {}),
      })
      setTransferBatch('')
    } catch (error) {
      setWorkflowError(error.message || `Could not ${action} transfer.`)
    }
  }

  async function handleAnalyticsExport() {
    try {
      const params = new URLSearchParams({
        branchId: activeBranchId,
        start: reportStart,
        end: reportEnd,
      })
      const response = await fetch(`/api/reports/movements.csv?${params}`, {
        credentials: 'include',
      })
      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || 'Could not export report.')
      }
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = 'pharmacy-stock-movements.csv'
      link.click()
      URL.revokeObjectURL(url)
    } catch (error) {
      setWorkflowError(error.message || 'Could not export report.')
    }
  }

  async function handleCreateProduct(event) {
    event.preventDefault()
    setWorkflowError('')
    try {
      await apiRequest('/api/products/create/', {
        method: 'POST',
        body: productForm,
      })
      setProductForm(emptyProduct)
      await refreshBranchData()
    } catch (error) {
      setWorkflowError(error.message || 'Could not create product.')
    }
  }

  async function handleCreateBarcodeAlias(event) {
    event.preventDefault()
    setWorkflowError('')
    try {
      await apiRequest('/api/barcode/aliases/', {
        method: 'POST',
        body: barcodeAliasForm,
      })
      setBarcodeAliasForm(emptyBarcodeAlias)
    } catch (error) {
      setWorkflowError(error.message || 'Could not add barcode alias.')
    }
  }

  async function handleCreateSupplier(event) {
    event.preventDefault()
    setWorkflowError('')
    try {
      await apiRequest('/api/suppliers/create/', {
        method: 'POST',
        body: supplierForm,
      })
      setSupplierForm(emptySupplier)
      await refreshBranchData()
    } catch (error) {
      setWorkflowError(error.message || 'Could not create supplier.')
    }
  }

  async function handleSetSupplierProduct(event) {
    event.preventDefault()
    setWorkflowError('')
    try {
      await apiRequest('/api/supplier-products/', {
        method: 'POST',
        body: {
          ...supplierProductForm,
          supplierId: Number(supplierProductForm.supplierId),
          leadTimeDays: Number(supplierProductForm.leadTimeDays),
        },
      })
      setSupplierProductForm(emptySupplierProduct)
      await refreshBranchData()
    } catch (error) {
      setWorkflowError(error.message || 'Could not configure supplier product.')
    }
  }

  const navPages = [
    'Overview',
    'Inventory',
    'Prescriptions',
    'Purchasing',
    'Suppliers',
    'Transfers',
    'Reports',
    ...(currentUser?.isStaff ? ['Administration'] : []),
  ]

  if (authLoading) {
    return <main className="auth-page">Checking your sign-in…</main>
  }

  if (!currentUser) {
    return (
      <LoginScreen
        username={loginUsername}
        setUsername={setLoginUsername}
        password={loginPassword}
        setPassword={setLoginPassword}
        error={authError}
        isSubmitting={loginSubmitting}
        onSubmit={handleLogin}
      />
    )
  }

  return (
    <div className={`app-layout${isSidebarCollapsed ? ' sidebar-collapsed' : ''}`}>
      <aside className="sidebar">
        <h2 className="sidebar-brand">Wellnest</h2>

        <button
          className="sidebar-toggle"
          type="button"
          onClick={() => setIsSidebarCollapsed((collapsed) => !collapsed)}
          aria-label={isSidebarCollapsed ? 'Show navigation' : 'Hide navigation'}
          aria-expanded={!isSidebarCollapsed}
          aria-controls="primary-navigation"
          title={isSidebarCollapsed ? 'Show navigation' : 'Hide navigation'}
        >
          <span aria-hidden="true">{isSidebarCollapsed ? '›' : '‹'}</span>
        </button>

        <nav id="primary-navigation" aria-label="Main navigation">
          {navPages.map((page) => (
            <button
              key={page}
              type="button"
              className={activePage === page ? 'nav-link active' : 'nav-link'}
              onClick={() => setActivePage(page)}
              aria-current={activePage === page ? 'page' : undefined}
              title={page}
            >
              <span className="nav-icon" aria-hidden="true">{page[0]}</span>
              <span className="nav-label">{page}</span>
            </button>
          ))}
        </nav>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <h1>
            {activePage === 'Overview' ? 'Pharmacy Inventory' : activePage}
          </h1>
          <div className="topbar-actions">
            {branches.length > 0 && (
              <label className="branch-select">
                Branch
                <select
                  value={activeBranchId}
                  onChange={(event) => {
                    setDataError('')
                    setActiveBranchId(event.target.value)
                  }}
                  aria-label="Active branch"
                >
                  {branches.map((branch) => (
                    <option key={branch.id} value={branch.id}>
                      {branch.code} — {branch.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <span>
              Signed in as {currentUser.firstName || currentUser.username}
            </span>
            <button type="button" onClick={handleLogout}>
              Sign out
            </button>
            {authError && <span className="auth-error" role="alert">{authError}</span>}
          </div>
        </header>

        <section className="dashboard">
          {dataError && <p className="form-error" role="alert">{dataError}</p>}
          {!dataError && branches.length === 0 && (
            <p className="form-error" role="alert">
              No active branch is assigned to your account. Ask an administrator to assign one.
            </p>
          )}
          {currentUser && activeBranchId && loadedBranchId !== activeBranchId && (
            <p role="status">Loading branch data…</p>
          )}
          {activePage === 'Overview' && (
            <>
              <h2>Good morning</h2>
              <p>Here’s an overview of your pharmacy stock.</p>

              <div className="summary-cards">
                <article className="summary-card">
                  <span>Total products</span>
                  <strong>{totalProducts}</strong>
                </article>

                <article className="summary-card">
                  <span>Low stock items</span>
                  <strong>{lowStockCount}</strong>
                </article>

                <article className="summary-card">
                  <span>Out of stock</span>
                  <strong>{outOfStockCount}</strong>
                </article>

                <article className="summary-card">
                  <span>Expiring within 90 days</span>
                  <strong>{expiringSoonCount}</strong>
                </article>

                <article className="summary-card">
                  <span>Expired stock</span>
                  <strong>{expiredCount}</strong>
                </article>
              </div>

              <section className="inventory-panel">
                <div className="inventory-heading">
                  <div>
                    <h2>Reorder suggestions</h2>
                    <p>Products at or below their reorder level.</p>
                  </div>
                </div>

                <table>
                  <thead>
                    <tr>
                      <th>SKU</th>
                      <th>Medicine</th>
                      <th>Current stock</th>
                      <th>Reorder level</th>
                      <th>Suggested order</th>
                    </tr>
                  </thead>

                  <tbody>
                    {reorderSuggestions.map((product) => (
                      <tr key={product.sku}>
                        <td>{product.sku}</td>
                        <td>{product.name}</td>
                        <td>{product.totalQuantity}</td>
                        <td>{product.reorderLevel}</td>
                        <td>{product.suggestedOrder}</td>
                      </tr>
                    ))}

                    {reorderSuggestions.length === 0 && (
                      <tr>
                        <td colSpan="5">
                          No products currently need reordering.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </section>
            </>
          )}

          {activePage === 'Inventory' && (
            <section className="inventory-panel">
              <div className="inventory-heading">
                <div>
                  <h2>Medicine inventory</h2>
                  <p>Check current stock levels.</p>
                </div>

                <input
                  className="inventory-search"
                  type="search"
                  placeholder="Search medicines..."
                  aria-label="Search medicines"
                  value={searchTerm}
                  onChange={(event) => setSearchTerm(event.target.value)}
                />

                <select
                  className="inventory-filter"
                  value={statusFilter}
                  onChange={(event) => setStatusFilter(event.target.value)}
                  aria-label="Filter by stock status"
                >
                  <option value="all">All statuses</option>
                  <option value="In stock">In stock</option>
                  <option value="Low stock">Low stock</option>
                  <option value="Out of stock">Out of stock</option>
                  <option value="Expired">Expired</option>
                </select>

                <form className="barcode-lookup" onSubmit={handleBarcodeLookup}>
                  <input
                    type="search"
                    value={barcodeInput}
                    onChange={(event) => setBarcodeInput(event.target.value)}
                    placeholder="Scan barcode or enter SKU"
                    aria-label="Scan barcode or enter SKU"
                    required
                  />
                  <button type="submit">Find</button>
                </form>

                <button
                  type="button"
                  onClick={() => setShowAddForm((shown) => !shown)}
                >
                  {showAddForm ? 'Close add form' : 'Add batch'}
                </button>

                <button
                  type="button"
                  onClick={() => setShowDispenseForm((shown) => !shown)}
                >
                  {showDispenseForm ? 'Close dispense form' : 'Dispense stock'}
                </button>

                <button
                  type="button"
                  onClick={() => setShowStockCountForm((shown) => !shown)}
                >
                  {showStockCountForm ? 'Close stock count' : 'Stock count'}
                </button>
              </div>

              {showAddForm && (
                <form className="batch-form" onSubmit={handleAddBatch}>
                  <label>
                    SKU
                    <input
                      name="sku"
                      value={newBatch.sku}
                      onChange={handleFormChange}
                      required
                    />
                  </label>

                  <label>
                    Medicine
                    <input
                      name="name"
                      value={newBatch.name}
                      onChange={handleFormChange}
                      required
                    />
                  </label>

                  <label>
                    Category
                    <input
                      name="category"
                      value={newBatch.category}
                      onChange={handleFormChange}
                      required
                    />
                  </label>

                  <label>
                    Batch number
                    <input
                      name="batch"
                      value={newBatch.batch}
                      onChange={handleFormChange}
                      required
                    />
                  </label>

                  <label>
                    Quantity
                    <input
                      name="quantity"
                      type="number"
                      min="0"
                      step="1"
                      value={newBatch.quantity}
                      onChange={handleFormChange}
                      required
                    />
                  </label>

                  <label>
                    Reorder level
                    <input
                      name="reorderLevel"
                      type="number"
                      min="0"
                      step="1"
                      value={newBatch.reorderLevel}
                      onChange={handleFormChange}
                      required
                    />
                  </label>

                  <label>
                    Purchase cost per unit
                    <input
                      name="purchaseCost"
                      type="number"
                      min="0"
                      step="0.01"
                      value={newBatch.purchaseCost}
                      onChange={handleFormChange}
                      required
                    />
                  </label>

                  <label>
                    Selling price per unit
                    <input
                      name="sellingPrice"
                      type="number"
                      min="0"
                      step="0.01"
                      value={newBatch.sellingPrice}
                      onChange={handleFormChange}
                      required
                    />
                  </label>

                  <label>
                    Expiry date
                    <input
                      name="expiry"
                      type="date"
                      value={newBatch.expiry}
                      onChange={handleFormChange}
                      required
                    />
                  </label>

                  <label>
                    Supplier / source
                    <input
                      name="supplier"
                      value={newBatch.supplier}
                      onChange={handleFormChange}
                      required
                    />
                  </label>

                  <label>
                    Receipt / invoice reference
                    <input
                      name="reference"
                      value={newBatch.reference}
                      onChange={handleFormChange}
                      required
                    />
                  </label>

                  {selectedBatchProduct?.isControlled && (
                    <label>Independent witness
                      <select name="witnessId" value={newBatch.witnessId} onChange={handleFormChange} required>
                        <option value="">Select witness</option>
                        {branchStaff.filter((member) => member.id !== currentUser.id).map((member) => <option key={member.id} value={member.id}>{member.name}</option>)}
                      </select>
                    </label>
                  )}

                  {formError && <p className="form-error">{formError}</p>}

                  <button type="submit">Save batch</button>
                </form>
              )}

              {showDispenseForm && (
                <form className="batch-form" onSubmit={handleDispense}>
                  <label>
                    Medicine
                    <select
                      name="sku"
                      value={dispenseForm.sku}
                      onChange={handleDispenseFormChange}
                      required
                    >
                      <option value="">Select medicine</option>
                      {[
                        ...new Map(
                          inventory.map((item) => [item.sku, item])
                        ).values(),
                      ].map((medicine) => (
                        <option key={medicine.sku} value={medicine.sku}>
                          {medicine.name}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label>
                    Transaction type
                    <select
                      name="transactionType"
                      value={dispenseForm.transactionType}
                      onChange={handleDispenseFormChange}
                      required
                    >
                      <option value="Sale">Sale</option>
                      <option value="Non-sale issue">Non-sale issue</option>
                    </select>
                  </label>

                  <label>
                    Quantity to dispense
                    <input
                      name="quantity"
                      type="number"
                      min="1"
                      step="1"
                      value={dispenseForm.quantity}
                      onChange={handleDispenseFormChange}
                      required
                    />
                  </label>

                  <label>
                    Supplied to
                    <input
                      name="recipient"
                      value={dispenseForm.recipient}
                      onChange={handleDispenseFormChange}
                      required
                    />
                  </label>

                  <label>
                    Sale / issue reference
                    <input
                      name="reference"
                      value={dispenseForm.reference}
                      onChange={handleDispenseFormChange}
                      required
                    />
                  </label>


                  {dispenseForm.transactionType === 'Sale' && (
                    <>
                      <label>
                        Amount received
                        <input
                          name="amountReceived"
                          type="number"
                          min="0"
                          step="0.01"
                          value={dispenseForm.amountReceived}
                          onChange={handleDispenseFormChange}
                          required
                        />
                      </label>

                      <label>
                        Payment method
                        <select
                          name="paymentMethod"
                          value={dispenseForm.paymentMethod}
                          onChange={handleDispenseFormChange}
                          required
                        >
                          <option value="">Select payment method</option>
                          <option value="Cash">Cash</option>
                          <option value="Mobile money">Mobile money</option>
                          <option value="Bank transfer">Bank transfer</option>
                          <option value="Card">Card</option>
                          <option value="Credit">Credit</option>
                        </select>
                      </label>
                    </>
                  )}
                  {dispenseError && (
                    <p className="form-error">{dispenseError}</p>
                  )}

                  <button type="submit">Record dispensing</button>
                </form>
              )}

              {showStockCountForm && (
                <form className="batch-form" onSubmit={handleStockCount}>
                  <label>
                    Batch to count
                    <select
                      name="batch"
                      value={stockCountForm.batch}
                      onChange={handleStockCountFormChange}
                      required
                    >
                      <option value="">Select a batch</option>
                      {inventory.map((medicine) => (
                        <option key={medicine.batch} value={medicine.batch}>
                          {medicine.name} — {medicine.batch} (recorded:{' '}
                          {medicine.quantity})
                        </option>
                      ))}
                    </select>
                  </label>

                  <label>
                    Quantity counted on shelf
                    <input
                      name="quantity"
                      type="number"
                      min="0"
                      step="1"
                      value={stockCountForm.quantity}
                      onChange={handleStockCountFormChange}
                      required
                    />
                  </label>

                  <label>
                    Reason for difference
                    <select
                      name="reason"
                      value={stockCountForm.reason}
                      onChange={handleStockCountFormChange}
                      required
                    >
                      <option value="">Select a reason</option>
                      <option value="Damaged stock">Damaged stock</option>
                      <option value="Expired stock">Expired stock</option>
                      <option value="Loss or theft">Loss or theft</option>
                      <option value="Counting correction">
                        Counting correction
                      </option>
                      <option value="Other">Other</option>
                    </select>
                  </label>

                  <label>
                    Count / adjustment reference
                    <input
                      name="reference"
                      value={stockCountForm.reference}
                      onChange={handleStockCountFormChange}
                      placeholder="For example: COUNT-2026-001"
                      required
                    />
                  </label>

                  {selectedCountBatch?.isControlled && (
                    <label>Independent witness
                      <select name="witnessId" value={stockCountForm.witnessId} onChange={handleStockCountFormChange} required>
                        <option value="">Select witness</option>
                        {branchStaff.filter((member) => member.id !== currentUser.id).map((member) => <option key={member.id} value={member.id}>{member.name}</option>)}
                      </select>
                    </label>
                  )}

                  {stockCountError && (
                    <p className="form-error">{stockCountError}</p>
                  )}

                  <button type="submit">Save stock count</button>
                </form>
              )}

              <table>
                <thead>
                  <tr>
                    <th>SKU</th>
                    <th>Medicine</th>
                    <th>Batch</th>
                    <th>Category</th>
                    <th>Quantity</th>
                    <th>Purchase cost / unit</th>
                    <th>Selling price / unit</th>
                    <th>Gross profit / unit</th>
                    <th>Expiry date</th>
                    <th>Status</th>
                  </tr>
                </thead>

                <tbody>
                  {filteredMedicines.map((medicine) => {
                    const status = getStockStatus(medicine, today)
                    const statusClass = {
                      'In stock': 'in-stock',
                      'Low stock': 'low-stock',
                      'Out of stock': 'out-of-stock',
                      Expired: 'expired',
                    }[status]

                    return (
                      <tr key={medicine.batch}>
                        <td>{medicine.sku}</td>
                        <td>{medicine.name}</td>
                        <td>{medicine.batch}</td>
                        <td>{medicine.category}</td>
                        <td>{medicine.quantity}</td>
                        <td>{Number(medicine.purchaseCost || 0).toLocaleString()}</td>
                        <td>{Number(medicine.sellingPrice || 0).toLocaleString()}</td>
                        <td>{(Number(medicine.sellingPrice || 0) - Number(medicine.purchaseCost || 0)).toLocaleString()}</td>
                        <td>{medicine.expiry}</td>
                        <td>
                          <span className={`stock-status ${statusClass}`}>
                            {status}
                          </span>
                        </td>
                      </tr>
                    )
                  })}

                  {filteredMedicines.length === 0 && (
                    <tr>
                      <td colSpan="10">No matching batches found.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </section>
          )}
          {activePage === 'Prescriptions' && (
            <>
              <section className="inventory-panel">
                <div className="inventory-heading">
                  <div>
                    <h2>Prescription intake</h2>
                    <p>
                      Store a minimum patient reference and prescriber details.
                      Verify a prescription before dispensing.
                    </p>
                  </div>
                </div>
                <form className="batch-form" onSubmit={handleCreatePrescription}>
                  <label>Prescription reference
                    <input value={prescriptionForm.reference} onChange={(event) => setPrescriptionForm((current) => ({ ...current, reference: event.target.value }))} required />
                  </label>
                  <label>Patient reference (avoid full names)
                    <input value={prescriptionForm.patientReference} onChange={(event) => setPrescriptionForm((current) => ({ ...current, patientReference: event.target.value }))} required />
                  </label>
                  <label>Prescriber
                    <input value={prescriptionForm.prescriberName} onChange={(event) => setPrescriptionForm((current) => ({ ...current, prescriberName: event.target.value }))} required />
                  </label>
                  <label>Registration reference
                    <input value={prescriptionForm.prescriberRegistration} onChange={(event) => setPrescriptionForm((current) => ({ ...current, prescriberRegistration: event.target.value }))} />
                  </label>
                  <label>Issue date
                    <input type="date" value={prescriptionForm.issuedDate} onChange={(event) => setPrescriptionForm((current) => ({ ...current, issuedDate: event.target.value }))} required />
                  </label>
                  <label>Expiry date (if stated)
                    <input type="date" value={prescriptionForm.expiresDate} onChange={(event) => setPrescriptionForm((current) => ({ ...current, expiresDate: event.target.value }))} />
                  </label>
                  <label>Product
                    <select value={prescriptionForm.sku} onChange={(event) => setPrescriptionForm((current) => ({ ...current, sku: event.target.value }))} required>
                      <option value="">Select product</option>
                      {products.map((product) => <option key={product.sku} value={product.sku}>{product.sku} — {product.name}{product.isControlled ? ' (controlled)' : product.requiresPrescription ? ' (prescription required)' : ''}</option>)}
                    </select>
                  </label>
                  <label>Quantity prescribed
                    <input type="number" min="1" step="1" value={prescriptionForm.quantity} onChange={(event) => setPrescriptionForm((current) => ({ ...current, quantity: event.target.value }))} required />
                  </label>
                  <label>Directions
                    <input value={prescriptionForm.directions} onChange={(event) => setPrescriptionForm((current) => ({ ...current, directions: event.target.value }))} />
                  </label>
                  <button type="submit">Save prescription</button>
                </form>
              </section>

              <section className="inventory-panel">
                <div className="inventory-heading"><div><h2>Prescription queue</h2><p>Verify, dispense against prescribed quantities, and review history.</p></div></div>
                <table>
                  <thead><tr><th>Reference</th><th>Patient reference</th><th>Prescriber</th><th>Items</th><th>Status</th><th>Action</th></tr></thead>
                  <tbody>
                    {prescriptions.map((prescription) => <tr key={prescription.id}>
                      <td>{prescription.reference}</td><td>{prescription.patientReference}</td><td>{prescription.prescriberName}</td>
                      <td>{prescription.lines.map((line) => `${line.name}: ${line.quantityDispensed}/${line.quantityPrescribed}${line.isControlled ? ' (controlled)' : ''}`).join('; ')}</td>
                      <td>{prescription.status}</td>
                      <td>{prescription.status === 'received' && <button type="button" onClick={() => handleVerifyPrescription(prescription.id)}>Verify</button>}</td>
                    </tr>)}
                    {prescriptions.length === 0 && <tr><td colSpan="6">No prescriptions recorded for this branch.</td></tr>}
                  </tbody>
                </table>
              </section>

              <section className="inventory-panel">
                <div className="inventory-heading"><div><h2>Dispense prescription item</h2><p>Unexpired lots are allocated FEFO; controlled items require a second branch member as witness.</p></div></div>
                <form className="batch-form" onSubmit={handlePrescriptionDispense}>
                  <label>Verified prescription item
                    <select value={prescriptionDispenseForm.lineKey} onChange={(event) => setPrescriptionDispenseForm((current) => ({ ...current, lineKey: event.target.value }))} required>
                      <option value="">Select an item</option>
                      {prescriptions.filter((item) => ['verified', 'partially_dispensed'].includes(item.status)).flatMap((prescription) => prescription.lines.filter((line) => line.quantityDispensed < line.quantityPrescribed).map((line) => <option key={`${prescription.id}:${line.id}`} value={`${prescription.id}:${line.id}`}>{prescription.reference} — {line.name} — remaining {line.quantityPrescribed - line.quantityDispensed}</option>))}
                    </select>
                  </label>
                  <label>Quantity
                    <input type="number" min="1" step="1" value={prescriptionDispenseForm.quantity} onChange={(event) => setPrescriptionDispenseForm((current) => ({ ...current, quantity: event.target.value }))} required />
                  </label>
                  <label>Amount received
                    <input type="number" min="0" step="0.01" value={prescriptionDispenseForm.amountReceived} onChange={(event) => setPrescriptionDispenseForm((current) => ({ ...current, amountReceived: event.target.value }))} required />
                  </label>
                  <label>Payment method
                    <select value={prescriptionDispenseForm.paymentMethod} onChange={(event) => setPrescriptionDispenseForm((current) => ({ ...current, paymentMethod: event.target.value }))} required>
                      <option value="">Select method</option><option>Cash</option><option>Mobile money</option><option>Bank transfer</option><option>Card</option><option>Credit</option>
                    </select>
                  </label>
                  <label>Dispense reference
                    <input value={prescriptionDispenseForm.reference} onChange={(event) => setPrescriptionDispenseForm((current) => ({ ...current, reference: event.target.value }))} required />
                  </label>
                  {selectedPrescriptionLine?.isControlled && <label>Independent witness
                    <select value={prescriptionDispenseForm.witnessId} onChange={(event) => setPrescriptionDispenseForm((current) => ({ ...current, witnessId: event.target.value }))} required>
                      <option value="">Select witness</option>
                      {branchStaff.filter((member) => member.id !== currentUser.id).map((member) => <option key={member.id} value={member.id}>{member.name} — {member.role}</option>)}
                    </select>
                  </label>}
                  {workflowError && <p className="form-error" role="alert">{workflowError}</p>}
                  <button type="submit">Dispense item</button>
                </form>
              </section>
            </>
          )}

          {activePage === 'Purchasing' && (
            <>
              {workflowError && <p className="form-error" role="alert">{workflowError}</p>}
              <section className="inventory-panel">
                <div className="inventory-heading"><div><h2>Reorder recommendations</h2><p>Suggestions use unexpired on-hand quantities and configured batch reorder points.</p></div></div>
                <table>
                  <thead><tr><th>SKU</th><th>Product</th><th>Available</th><th>Reorder point</th><th>Suggested</th><th>Preferred supplier</th><th>Action</th></tr></thead>
                  <tbody>{reorderSuggestions.map((item) => <tr key={item.sku}>
                    <td>{item.sku}</td><td>{item.name}</td><td>{item.onHand}</td><td>{item.reorderLevel}</td><td>{item.suggestedQuantity}</td><td>{item.supplier || 'Not configured'}</td>
                    <td>{canManageBranch && item.supplierId
                      ? <button type="button" onClick={() => handleCreateReorderDraft(item.sku)}>Create draft PO</button>
                      : !item.supplierId ? 'Configure supplier mapping' : 'Manager permission required'}</td>
                  </tr>)}{!reorderSuggestions.length && <tr><td colSpan="7">No products currently need reordering.</td></tr>}</tbody>
                </table>
              </section>

              <section className="inventory-panel">
                <div className="inventory-heading"><div><h2>Purchase order</h2><p>Create and submit an order; only branch managers can create or receive orders.</p></div></div>
                {canManageBranch ? <form className="batch-form" onSubmit={handleCreatePurchaseOrder}>
                  <label>Order reference<input value={purchaseOrderForm.number} onChange={(event) => setPurchaseOrderForm((current) => ({ ...current, number: event.target.value }))} required /></label>
                  <label>Supplier<select value={purchaseOrderForm.supplierId} onChange={(event) => setPurchaseOrderForm((current) => ({ ...current, supplierId: event.target.value }))} required><option value="">Select supplier</option>{suppliers.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
                  <label>Expected date<input type="date" value={purchaseOrderForm.expectedDate} onChange={(event) => setPurchaseOrderForm((current) => ({ ...current, expectedDate: event.target.value }))} /></label>
                  <label>Product<select value={purchaseOrderForm.sku} onChange={(event) => setPurchaseOrderForm((current) => ({ ...current, sku: event.target.value }))} required><option value="">Select product</option>{products.map((item) => <option key={item.sku} value={item.sku}>{item.sku} — {item.name}</option>)}</select></label>
                  <label>Quantity<input type="number" min="1" step="1" value={purchaseOrderForm.quantity} onChange={(event) => setPurchaseOrderForm((current) => ({ ...current, quantity: event.target.value }))} required /></label>
                  <label>Unit cost<input type="number" min="0" step="0.01" value={purchaseOrderForm.unitCost} onChange={(event) => setPurchaseOrderForm((current) => ({ ...current, unitCost: event.target.value }))} required /></label>
                  <button type="submit">Submit purchase order</button>
                </form> : <p className="form-error">Branch manager permission is required.</p>}
                {purchaseReceiptForm.orderId && <form className="batch-form" onSubmit={handleReceivePurchaseOrder}>
                  <h3>Receive against order {purchaseReceiptForm.orderId}</h3>
                  <label>Received quantity<input type="number" min="1" step="1" value={purchaseReceiptForm.quantity} onChange={(event) => setPurchaseReceiptForm((current) => ({ ...current, quantity: event.target.value }))} required /></label>
                  <label>Lot number<input value={purchaseReceiptForm.batch} onChange={(event) => setPurchaseReceiptForm((current) => ({ ...current, batch: event.target.value }))} required /></label>
                  <label>Expiry date<input type="date" value={purchaseReceiptForm.expiry} onChange={(event) => setPurchaseReceiptForm((current) => ({ ...current, expiry: event.target.value }))} required /></label>
                  <label>Retail price per unit<input type="number" min="0" step="0.01" value={purchaseReceiptForm.sellingPrice} onChange={(event) => setPurchaseReceiptForm((current) => ({ ...current, sellingPrice: event.target.value }))} required /></label>
                  {selectedReceiptLine?.isControlled && <label>Independent witness<select value={purchaseReceiptForm.witnessId} onChange={(event) => setPurchaseReceiptForm((current) => ({ ...current, witnessId: event.target.value }))} required><option value="">Select witness</option>{branchStaff.filter((member) => member.id !== currentUser.id).map((member) => <option key={member.id} value={member.id}>{member.name}</option>)}</select></label>}
                  <button type="submit">Receive stock</button>
                  <button type="button" onClick={() => setPurchaseReceiptForm(emptyPurchaseReceipt)}>Cancel</button>
                </form>}
              </section>

              <section className="inventory-panel">
                <div className="inventory-heading"><div><h2>Purchase orders</h2><p>Record actual quantities, lots, expiry, and retail price when stock arrives.</p></div></div>
                <table><thead><tr><th>Order</th><th>Supplier</th><th>Product lines</th><th>Status</th><th>Actions</th></tr></thead><tbody>
                  {purchaseOrders.map((order) => <tr key={order.id}><td>{order.number}</td><td>{order.supplier}</td><td>{order.lines.map((line) => `${line.sku}: ${line.quantityReceived}/${line.quantityOrdered}`).join('; ')}</td><td>{order.status}</td><td>{canManageBranch && order.status === 'draft' && <button type="button" onClick={() => handleSubmitPurchaseOrder(order.id)}>Submit order</button>}{canManageBranch && ['submitted', 'partially_received'].includes(order.status) && order.lines.filter((line) => line.quantityReceived < line.quantityOrdered).map((line) => <button key={line.id} type="button" onClick={() => setPurchaseReceiptForm({ orderId: String(order.id), lineId: String(line.id), quantity: String(line.quantityOrdered - line.quantityReceived), batch: '', expiry: '', sellingPrice: '', witnessId: '' })}>Receive {line.sku}</button>)}</td></tr>)}
                  {!purchaseOrders.length && <tr><td colSpan="5">No purchase orders for this branch.</td></tr>}
                </tbody></table>
              </section>
            </>
          )}

          {activePage === 'Transfers' && (
            <>
              <section className="inventory-panel">
                <div className="inventory-heading"><div><h2>Request branch transfer</h2><p>Transfers require manager permissions at each branch. Stock moves on dispatch and is received into a destination lot.</p></div></div>
                {canManageBranch ? <form className="batch-form" onSubmit={handleCreateTransfer}>
                  <label>Destination branch<select value={transferForm.destinationBranchId} onChange={(event) => setTransferForm((current) => ({ ...current, destinationBranchId: event.target.value }))} required><option value="">Select branch</option>{branches.filter((item) => String(item.id) !== String(activeBranchId)).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
                  <label>Reference<input value={transferForm.reference} onChange={(event) => setTransferForm((current) => ({ ...current, reference: event.target.value }))} required /></label>
                  <label>Product<select value={transferForm.sku} onChange={(event) => setTransferForm((current) => ({ ...current, sku: event.target.value }))} required><option value="">Select product</option>{products.map((item) => <option key={item.sku} value={item.sku}>{item.sku} — {item.name}</option>)}</select></label>
                  <label>Quantity<input type="number" min="1" step="1" value={transferForm.quantity} onChange={(event) => setTransferForm((current) => ({ ...current, quantity: event.target.value }))} required /></label>
                  {selectedTransferProduct?.isControlled && <label>Independent witness<select value={transferForm.witnessId} onChange={(event) => setTransferForm((current) => ({ ...current, witnessId: event.target.value }))} required><option value="">Select witness at dispatch</option>{branchStaff.filter((member) => member.id !== currentUser.id).map((member) => <option key={member.id} value={member.id}>{member.name}</option>)}</select></label>}
                  <button type="submit">Request transfer</button>
                </form> : <p className="form-error">Branch manager permission is required.</p>}
              </section>
              <section className="inventory-panel">
                <div className="inventory-heading"><div><h2>Branch transfers</h2><p>Dispatch from source and confirm receipt at destination.</p></div></div>
                <label className="transfer-lot-input">Destination lot number (optional)
                  <input value={transferBatch} onChange={(event) => setTransferBatch(event.target.value)} placeholder="Defaults to source lot" />
                </label>
                {transfers.some((item) => (item.status === 'dispatched' && String(item.destinationBranchId) === String(activeBranchId) || item.status === 'requested' && String(item.sourceBranchId) === String(activeBranchId)) && item.lines.some((line) => line.isControlled)) && <label className="transfer-lot-input">Controlled stock movement witness
                  <select value={transferWitnessId} onChange={(event) => setTransferWitnessId(event.target.value)}><option value="">Select witness</option>{branchStaff.filter((member) => member.id !== currentUser.id).map((member) => <option key={member.id} value={member.id}>{member.name}</option>)}</select>
                </label>}
                <table><thead><tr><th>Reference</th><th>From</th><th>To</th><th>Items</th><th>Status</th><th>Action</th></tr></thead><tbody>
                  {transfers.map((item) => <tr key={item.id}><td>{item.reference}</td><td>{item.sourceBranch}</td><td>{item.destinationBranch}</td><td>{item.lines.map((line) => `${line.sku} ${line.quantityDispatched}`).join('; ')}</td><td>{item.status}</td>
                    <td>{canManageBranch && item.status === 'requested' && String(item.sourceBranchId) === String(activeBranchId) && <button type="button" onClick={() => handleTransferAction(item.id, 'dispatch')}>Dispatch</button>}{canManageBranch && item.status === 'dispatched' && String(item.destinationBranchId) === String(activeBranchId) && <button type="button" onClick={() => handleTransferAction(item.id, 'receive')}>Confirm receipt</button>}</td>
                  </tr>)}
                  {!transfers.length && <tr><td colSpan="6">No transfers involving this branch.</td></tr>}
                </tbody></table>
              </section>
            </>
          )}

          {activePage === 'Suppliers' && (
            <>
              <section className="inventory-panel">
                <div className="inventory-heading">
                  <div>
                    <h2>Supplier invoices</h2>
                    <p>Track invoice totals, due dates, payments, and balances.</p>
                  </div>
                  {canManageBranch && <button type="button" onClick={() => setShowSupplierInvoiceForm((shown) => !shown)}>
                    {showSupplierInvoiceForm ? 'Close invoice form' : 'Add supplier invoice'}
                  </button>
                  }
                  {canManageBranch && <button type="button" onClick={() => setShowSupplierPaymentForm((shown) => !shown)}>
                    {showSupplierPaymentForm ? 'Close payment form' : 'Record payment'}
                  </button>
                  }
                </div>

                {showSupplierInvoiceForm && canManageBranch && (
                  <form className="batch-form" onSubmit={handleSaveSupplierInvoice}>
                    <label>Supplier<input name="supplier" value={supplierInvoiceForm.supplier} onChange={handleSupplierInvoiceChange} required /></label>
                    <label>Invoice number<input name="invoiceNumber" value={supplierInvoiceForm.invoiceNumber} onChange={handleSupplierInvoiceChange} required /></label>
                    <label>Invoice total<input name="invoiceAmount" type="number" min="0.01" step="0.01" value={supplierInvoiceForm.invoiceAmount} onChange={handleSupplierInvoiceChange} required /></label>
                    <label>Amount already paid<input name="amountPaid" type="number" min="0" step="0.01" value={supplierInvoiceForm.amountPaid} onChange={handleSupplierInvoiceChange} required /></label>
                    <label>Due date<input name="dueDate" type="date" value={supplierInvoiceForm.dueDate} onChange={handleSupplierInvoiceChange} required /></label>
                    <label>Linked purchase order (optional)<select name="purchaseOrderId" value={supplierInvoiceForm.purchaseOrderId} onChange={handleSupplierInvoiceChange}><option value="">No linked order</option>{purchaseOrders.map((order) => <option key={order.id} value={order.id}>{order.number} — {order.supplier} ({order.status})</option>)}</select></label>
                    {supplierInvoiceError && <p className="form-error">{supplierInvoiceError}</p>}
                    <button type="submit">Save invoice</button>
                  </form>
                )}

                {showSupplierPaymentForm && canManageBranch && (
                  <form className="batch-form" onSubmit={handleRecordSupplierPayment}>
                    <label>Invoice<select name="invoiceId" value={supplierPaymentForm.invoiceId} onChange={handleSupplierPaymentChange} required>
                      <option value="">Select an unpaid invoice</option>
                      {supplierInvoices.filter((invoice) => invoice.invoiceAmount > invoice.amountPaid).map((invoice) => (
                        <option key={invoice.id} value={invoice.id}>{invoice.supplier} — {invoice.invoiceNumber} — balance {((invoice.invoiceAmount - invoice.amountPaid).toLocaleString())}</option>
                      ))}
                    </select></label>
                    <label>Payment amount<input name="amount" type="number" min="0.01" step="0.01" value={supplierPaymentForm.amount} onChange={handleSupplierPaymentChange} required /></label>
                    <label>Payment method<select name="method" value={supplierPaymentForm.method} onChange={handleSupplierPaymentChange} required>
                      <option value="">Select method</option><option value="Cash">Cash</option><option value="Mobile money">Mobile money</option><option value="Bank transfer">Bank transfer</option><option value="Card">Card</option>
                    </select></label>
                    <label>Payment reference<input name="reference" value={supplierPaymentForm.reference} onChange={handleSupplierPaymentChange} required /></label>
                    {supplierPaymentError && <p className="form-error">{supplierPaymentError}</p>}
                    <button type="submit">Save payment</button>
                  </form>
                )}

                <table>
                  <thead><tr><th>Supplier</th><th>Invoice</th><th>Invoice total</th><th>Paid</th><th>Balance</th><th>Due date</th><th>Status</th></tr></thead>
                  <tbody>
                    {supplierInvoices.map((invoice) => {
                      const balance = invoice.invoiceAmount - invoice.amountPaid
                      const status = getSupplierInvoiceStatus(invoice)
                      return <tr key={invoice.id}>
                        <td>{invoice.supplier}</td><td>{invoice.invoiceNumber}</td>
                        <td>{invoice.invoiceAmount.toLocaleString()}</td><td>{invoice.amountPaid.toLocaleString()}</td>
                        <td>{balance.toLocaleString()}</td><td>{invoice.dueDate}</td><td>{status}</td>
                      </tr>
                    })}
                    {supplierInvoices.length === 0 && <tr><td colSpan="7">No supplier invoices recorded yet.</td></tr>}
                  </tbody>
                </table>
              </section>

              <section className="inventory-panel">
                <div className="inventory-heading"><div><h2>Supplier payment history</h2><p>Payments entered against supplier invoices.</p></div></div>
                <table>
                  <thead><tr><th>Date</th><th>Supplier</th><th>Invoice</th><th>Amount</th><th>Method</th><th>Reference</th></tr></thead>
                  <tbody>
                    {supplierPayments.map((payment) => <tr key={payment.id}>
                      <td>{new Date(payment.recordedAt).toLocaleString()}</td><td>{payment.supplier}</td><td>{payment.invoiceNumber}</td><td>{payment.amount.toLocaleString()}</td><td>{payment.method}</td><td>{payment.reference}</td>
                    </tr>)}
                    {supplierPayments.length === 0 && <tr><td colSpan="6">No supplier payments recorded yet.</td></tr>}
                  </tbody>
                </table>
              </section>

              <section className="inventory-panel">
                <div className="inventory-heading"><div><h2>Received stock by supplier</h2><p>Receipt records created when batches were added.</p></div></div>
                <table>
                  <thead><tr><th>Supplier</th><th>Medicine</th><th>Batch</th><th>Quantity received</th><th>Reference</th></tr></thead>
                  <tbody>
                    {stockMovements.filter((movement) => movement.type === 'Received').map((movement) => <tr key={movement.id}>
                      <td>{movement.supplier}</td><td>{movement.name}</td><td>{movement.batch}</td><td>{movement.quantity}</td><td>{movement.reference}</td>
                    </tr>)}
                    {!stockMovements.some((movement) => movement.type === 'Received') && <tr><td colSpan="5">No supplier receipts recorded yet.</td></tr>}
                  </tbody>
                </table>
              </section>
            </>
          )}

          {activePage === 'Administration' && currentUser.isStaff && (
            <>
              <section className="inventory-panel">
                <div className="inventory-heading"><div><h2>Medication catalog</h2><p>Set the locally configured prescription and controlled flags; they block ordinary sales.</p></div></div>
                <form className="batch-form" onSubmit={handleCreateProduct}>
                  <label>SKU<input value={productForm.sku} onChange={(event) => setProductForm((current) => ({ ...current, sku: event.target.value }))} required /></label>
                  <label>Name<input value={productForm.name} onChange={(event) => setProductForm((current) => ({ ...current, name: event.target.value }))} required /></label>
                  <label>Category<input value={productForm.category} onChange={(event) => setProductForm((current) => ({ ...current, category: event.target.value }))} required /></label>
                  <label>Dispensing unit<input value={productForm.unit} onChange={(event) => setProductForm((current) => ({ ...current, unit: event.target.value }))} required /></label>
                  <label>Primary barcode<input value={productForm.barcode} onChange={(event) => setProductForm((current) => ({ ...current, barcode: event.target.value }))} /></label>
                  <label className="checkbox-label"><input type="checkbox" checked={productForm.requiresPrescription} onChange={(event) => setProductForm((current) => ({ ...current, requiresPrescription: event.target.checked }))} /> Prescription required</label>
                  <label className="checkbox-label"><input type="checkbox" checked={productForm.isControlled} onChange={(event) => setProductForm((current) => ({ ...current, isControlled: event.target.checked }))} /> Controlled medicine</label>
                  <label>Controlled schedule (as configured)
                    <input value={productForm.controlledSchedule} onChange={(event) => setProductForm((current) => ({ ...current, controlledSchedule: event.target.value }))} />
                  </label>
                  <button type="submit">Add catalog product</button>
                </form>
              </section>
              <section className="inventory-panel">
                <div className="inventory-heading"><div><h2>Barcode alias</h2><p>Assign alternate package barcodes to an existing product.</p></div></div>
                <form className="batch-form" onSubmit={handleCreateBarcodeAlias}>
                  <label>Product<select value={barcodeAliasForm.sku} onChange={(event) => setBarcodeAliasForm((current) => ({ ...current, sku: event.target.value }))} required><option value="">Select product</option>{products.map((item) => <option key={item.sku} value={item.sku}>{item.sku} — {item.name}</option>)}</select></label>
                  <label>Barcode value<input value={barcodeAliasForm.value} onChange={(event) => setBarcodeAliasForm((current) => ({ ...current, value: event.target.value }))} required /></label>
                  <label>Symbology (optional)<input value={barcodeAliasForm.symbology} onChange={(event) => setBarcodeAliasForm((current) => ({ ...current, symbology: event.target.value }))} /></label>
                  <button type="submit">Add barcode alias</button>
                </form>
              </section>
              <section className="inventory-panel">
                <div className="inventory-heading"><div><h2>Supplier directory</h2><p>Maintain suppliers for purchase orders.</p></div></div>
                <form className="batch-form" onSubmit={handleCreateSupplier}>
                  <label>Supplier name<input value={supplierForm.name} onChange={(event) => setSupplierForm((current) => ({ ...current, name: event.target.value }))} required /></label>
                  <label>Contact name<input value={supplierForm.contactName} onChange={(event) => setSupplierForm((current) => ({ ...current, contactName: event.target.value }))} /></label>
                  <label>Email<input type="email" value={supplierForm.email} onChange={(event) => setSupplierForm((current) => ({ ...current, email: event.target.value }))} /></label>
                  <label>Phone<input value={supplierForm.phone} onChange={(event) => setSupplierForm((current) => ({ ...current, phone: event.target.value }))} /></label>
                  <label>Address<input value={supplierForm.address} onChange={(event) => setSupplierForm((current) => ({ ...current, address: event.target.value }))} /></label>
                  <button type="submit">Add supplier</button>
                </form>
              </section>
              <section className="inventory-panel">
                <div className="inventory-heading"><div><h2>Supplier product terms</h2><p>Configure supplier SKU, unit cost, lead time, and the preferred supplier used for reorder drafts.</p></div></div>
                <form className="batch-form" onSubmit={handleSetSupplierProduct}>
                  <label>Product<select value={supplierProductForm.sku} onChange={(event) => setSupplierProductForm((current) => ({ ...current, sku: event.target.value }))} required><option value="">Select product</option>{products.map((item) => <option key={item.sku} value={item.sku}>{item.sku} — {item.name}</option>)}</select></label>
                  <label>Supplier<select value={supplierProductForm.supplierId} onChange={(event) => setSupplierProductForm((current) => ({ ...current, supplierId: event.target.value }))} required><option value="">Select supplier</option>{suppliers.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
                  <label>Supplier SKU<input value={supplierProductForm.supplierSku} onChange={(event) => setSupplierProductForm((current) => ({ ...current, supplierSku: event.target.value }))} /></label>
                  <label>Unit cost<input type="number" min="0" step="0.01" value={supplierProductForm.unitCost} onChange={(event) => setSupplierProductForm((current) => ({ ...current, unitCost: event.target.value }))} required /></label>
                  <label>Lead time (days)<input type="number" min="0" step="1" value={supplierProductForm.leadTimeDays} onChange={(event) => setSupplierProductForm((current) => ({ ...current, leadTimeDays: event.target.value }))} required /></label>
                  <label className="checkbox-label"><input type="checkbox" checked={supplierProductForm.isPreferred} onChange={(event) => setSupplierProductForm((current) => ({ ...current, isPreferred: event.target.checked }))} /> Preferred supplier</label>
                  <button type="submit">Save supplier product terms</button>
                </form>
                {workflowError && <p className="form-error" role="alert">{workflowError}</p>}
              </section>
            </>
          )}

          {activePage === 'Reports' && (
            <>
              <section className="inventory-panel">
                <div className="inventory-heading">
                  <div><h2>Operational analytics</h2><p>Movement and sales totals for the selected branch and date range. Values are operational summaries, not statutory reports.</p></div>
                  <button type="button" onClick={handleAnalyticsExport}>Export movement CSV</button>
                </div>
                <div className="report-filters">
                  <label>From<input type="date" value={reportStart} onChange={(event) => setReportStart(event.target.value)} /></label>
                  <label>To<input type="date" value={reportEnd} onChange={(event) => setReportEnd(event.target.value)} /></label>
                </div>
                {workflowError && <p className="form-error" role="alert">{workflowError}</p>}
                {analytics && <>
                  <div className="summary-cards">
                    <article className="summary-card"><span>Received units</span><strong>{analytics.summary.unitsReceived}</strong></article>
                    <article className="summary-card"><span>Issued units</span><strong>{analytics.summary.unitsIssued}</strong></article>
                    <article className="summary-card"><span>Sales total</span><strong>{analytics.summary.salesAmount.toLocaleString()}</strong></article>
                    <article className="summary-card"><span>Gross profit</span><strong>{analytics.summary.grossProfit.toLocaleString()}</strong></article>
                    <article className="summary-card"><span>Open balances</span><strong>{analytics.summary.outstandingBalance.toLocaleString()}</strong></article>
                  </div>
                  <div className="inventory-heading"><div><h2>Controlled medicine register</h2><p>Witness entries associated with recorded controlled stock movements.</p></div></div>
                  <table><thead><tr><th>Date</th><th>Product</th><th>Lot</th><th>Movement</th><th>Quantity</th><th>Witness</th><th>Balance after</th><th>Reference</th></tr></thead><tbody>
                    {analytics.controlledRegister.map((row, index) => <tr key={`${row.reference}-${index}`}><td>{new Date(row.date).toLocaleString()}</td><td>{row.product}</td><td>{row.batch}</td><td>{row.movement}</td><td>{row.quantity}</td><td>{row.witness}</td><td>{row.balanceAfter}</td><td>{row.reference}</td></tr>)}
                    {!analytics.controlledRegister.length && <tr><td colSpan="8">No controlled dispensing entries for this period.</td></tr>}
                  </tbody></table>
                </>}
              </section>

              <section className="inventory-panel movement-panel">
              <div className="inventory-heading">
                <div>
                  <h2>Recent stock activity</h2>
                  <p>Track received, dispensed, and stock-count adjustments.</p>
                </div>
              </div>

              <table>
                <thead>
                  <tr>
                    <th>Date and time</th>
                    <th>Activity</th>
                    <th>Medicine</th>
                    <th>Batch</th>
                    <th>Quantity change</th>
                    <th>Supplier / recipient / reason</th>
                    <th>Reference</th>
                  </tr>
                </thead>

                <tbody>
                  {stockMovements.map((movement) => (
                    <tr key={movement.id}>
                      <td>{new Date(movement.recordedAt).toLocaleString()}</td>
                      <td>{movement.type}</td>
                      <td>{movement.name}</td>
                      <td>{movement.batch}</td>
                      <td>
                        {movement.quantity > 0 ? '+' : ''}
                        {movement.quantity}
                      </td>
                      <td>
                        {movement.recipient || movement.supplier || '—'}
                      </td>
                      <td>{movement.reference}</td>
                    </tr>
                  ))}

                  {stockMovements.length === 0 && (
                    <tr>
                      <td colSpan="7">No stock activity recorded yet.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </section>

              <section className="inventory-panel">
                <div className="inventory-heading">
                  <div>
                    <h2>Sales and payments</h2>
                    <p>Recorded sales, amounts received, and outstanding balances.</p>
                  </div>
                  <button type="button" onClick={() => setShowCustomerPaymentForm((shown) => !shown)}>
                    {showCustomerPaymentForm ? 'Close payment form' : 'Record customer payment'}
                  </button>
                </div>

                {showCustomerPaymentForm && (
                  <form className="batch-form" onSubmit={handleRecordCustomerPayment}>
                    <label>Outstanding sale
                      <select name="saleId" value={customerPaymentForm.saleId} onChange={handleCustomerPaymentChange} required>
                        <option value="">Select a sale with a balance</option>
                        {sales.filter((sale) => sale.balanceDue > 0).map((sale) => (
                          <option key={sale.id} value={sale.id}>
                            {sale.recipient} — {sale.name} — {sale.reference} — due {sale.balanceDue.toLocaleString()}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>Payment amount
                      <input name="amount" type="number" min="0.01" step="0.01" value={customerPaymentForm.amount} onChange={handleCustomerPaymentChange} required />
                    </label>
                    <label>Payment method
                      <select name="method" value={customerPaymentForm.method} onChange={handleCustomerPaymentChange} required>
                        <option value="">Select method</option>
                        <option value="Cash">Cash</option>
                        <option value="Mobile money">Mobile money</option>
                        <option value="Bank transfer">Bank transfer</option>
                        <option value="Card">Card</option>
                      </select>
                    </label>
                    <label>Payment reference
                      <input name="reference" value={customerPaymentForm.reference} onChange={handleCustomerPaymentChange} required />
                    </label>
                    {customerPaymentError && <p className="form-error">{customerPaymentError}</p>}
                    <button type="submit">Save customer payment</button>
                  </form>
                )}

                <table>
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Medicine</th>
                      <th>Quantity</th>
                      <th>Sale total</th>
                      <th>Gross profit</th>
                      <th>Received</th>
                      <th>Balance due</th>
                      <th>Payment status</th>
                      <th>Original payment method</th>
                      <th>Reference</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sales.map((sale) => (
                      <tr key={sale.id}>
                        <td>{new Date(sale.recordedAt).toLocaleString()}</td>
                        <td>{sale.name}</td>
                        <td>{sale.quantity}</td>
                        <td>{sale.saleAmount.toLocaleString()}</td>
                        <td>{sale.grossProfit.toLocaleString()}</td>
                        <td>{sale.amountReceived.toLocaleString()}</td>
                        <td>{sale.balanceDue.toLocaleString()}</td>
                        <td>{getSalePaymentStatus(sale)}</td>
                        <td>{sale.paymentMethod}</td>
                        <td>{sale.reference}</td>
                      </tr>
                    ))}
                    {sales.length === 0 && (
                      <tr>
                        <td colSpan="10">No sales recorded yet.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </section>
              <section className="inventory-panel">
                <div className="inventory-heading">
                  <div>
                    <h2>Customer payment history</h2>
                    <p>Later payments recorded against sales.</p>
                  </div>
                </div>
                <table>
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Customer</th>
                      <th>Sale reference</th>
                      <th>Amount</th>
                      <th>Method</th>
                      <th>Payment reference</th>
                    </tr>
                  </thead>
                  <tbody>
                    {customerPayments.map((payment) => (
                      <tr key={payment.id}>
                        <td>{new Date(payment.recordedAt).toLocaleString()}</td>
                        <td>{payment.customer}</td>
                        <td>{payment.saleReference}</td>
                        <td>{payment.amount.toLocaleString()}</td>
                        <td>{payment.method}</td>
                        <td>{payment.reference}</td>
                      </tr>
                    ))}
                    {customerPayments.length === 0 && (
                      <tr><td colSpan="6">No later customer payments recorded yet.</td></tr>
                    )}
                  </tbody>
                </table>
              </section>

            </>
          )}
        </section>
      </main>
    </div>
  )
}

export default App
