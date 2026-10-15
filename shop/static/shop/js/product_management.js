var urlConfig = {
    'fetchProductFromOpenFood': '/shop/products/fetch-product/',
    'getSubCategories': '/shop/products/get-sub-categories/',
    'fetchProductByBarcode': '/shop/products/fetch-product-by-barcode/',
    'exportProducts': '/shop/products/export-excel/',
    'marketingOptedUsers': '/shop/users/fetch-marketing-opted-users',
    'baseUrl': '/shop/product-management/'

}

function setValueIfNotNull(elementId, value) {
    if (value !== null) {
        document.getElementById(elementId).value = value
    }
}

// Function to fetch product details from open food for product add form
function fetchProductDetailsFromOpenFood(barcode) {
    var url = urlConfig.fetchProductFromOpenFood + "?barcode=" + barcode
    fetch(url)
        .then((response) => {
            if (!response.ok) {
                throw new Error('Error fetching product details. Please enter the details manually.')
            }
            return response.json()
        })
        .then((data) => {
            setValueIfNotNull('name_product_add', data.product.product_name)
            setValueIfNotNull('ingredients_product_add', data.product.ingredients_text_en)
            setValueIfNotNull('allergens_product_add', data.product.allergens)

            var fetchSuccessMessageElement = document.getElementById('fetch_call_response_message_product_add')
            fetchSuccessMessageElement.className = 'text-center text-success mb-3'
            fetchSuccessMessageElement.innerText = 'Populated product details successfully'
            fetchSuccessMessageElement.style.display = 'block'
        })
        .catch((error) => {
            var errorMessageElement = document.getElementById('fetch_call_response_message_product_add')
            errorMessageElement.innerText = error.message
            errorMessageElement.className = 'text-center text-danger mb-3'
            errorMessageElement.style.display = 'block'
        })
}

// Function to fetch product details from the database
async function fetchProductByBarcode(barcode) {
    // Set URL for fetching product details
    const fetchProductUrl = urlConfig.fetchProductByBarcode + "?barcode=" + barcode;

    if (barcode) {
        try {
            // Fetch product details using Fetch API
            const response = await fetch(fetchProductUrl);
            // Check if the response is ok (status code 200-299)
            if (!response.ok) {
                throw new Error(`Error while fetching product information`);
            }

            const productData = await response.json();
            return productData;
        } catch (error) {
            console.error('Error fetching product details:', error);
            alert(error);
        }
    } else {
        console.error("Barcode missing");
    }
}

async function approveProduct(productId) {
    const approveProductUrl = window.location.origin + `/shop/products/${productId}/approve/`;

    if (!productId) {
        console.error("Product ID is missing");
        return { success: false, message: "Product ID is required" };
    }

    try {
        let response = await fetch(approveProductUrl, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRF-Token": "{{csrf_token}}" // Ensure CSRF token is valid
            },
            body: JSON.stringify({ product_id: productId })
        });

        if (!response.ok) {
            throw new Error(`API responded with status ${response.status}`);
        }

        let data = await response.json(); // Assuming the API returns JSON
        return { success: true, data };
    } catch (error) {
        console.error("Error while approving product:", error);
        return { success: false, message: error.message };
    }
}


// Restrict product image file size to 2MB
function checkFileSize(input) {
    if (input.files && input.files[0]) {
        const fileSize = input.files[0].size // Size in bytes
        const maxSizeInBytes = 2 * 1024 * 1024

        if (fileSize > maxSizeInBytes) {
            alert('File size exceeds the maximum allowed size (2MB). Please choose a smaller file.')
            input.value = '' // Clear the file input to allow selecting a different file
        }
    }
}

function handleCategoryChange(categoryElement, subCategoryElement) {
    categoryElement.addEventListener('change', function () {

        console.log("Category Select in product update form changed")
        var categoryId = categoryElement.value
        var url = urlConfig.getSubCategories + "?category_id=" + categoryId

        fetch(url)
            .then((response) => response.json())
            .then((data) => {
                subCategoryElement.innerHTML = '<option value="">Select Sub Category</option>'
                data.forEach((subCategory) => {
                    var option = document.createElement('option')
                    option.value = subCategory.id
                    option.textContent = subCategory.name
                    subCategoryElement.appendChild(option)
                })
            })
            .catch((error) => console.error('Error:', error))
    })
}


function exportProductsExcel() {

    console.log("Export button clicked")

    var url = urlConfig.exportProducts;
    window.open(url, '_blank');

}

function exportMarketingOptedUsers() {
    console.log("Marketing Opted users clicked")
    var url = urlConfig.marketingOptedUsers
    window.open(url, '_blank')
}

function applyQuickFilter(filterType) {
    const baseUrl = window.location.origin + window.location.pathname;
    const url = new URL(baseUrl);
    url.searchParams.append('filter_type', filterType);
    window.location.href = url;
}

function applyCategoryFilter(categoryName) {
    const baseUrl = window.location.origin + urlConfig.baseUrl + categoryName.toLowerCase();
    console.log(baseUrl);
    const url = new URL(baseUrl);
    window.location.href = url;
}

function removeAllFilters() {
    const baseUrl = window.location.origin + window.location.pathname;
    const url = new URL(baseUrl);
    window.location.href = url;
}



function initialize() {

    // if quick filters have been applied, update the quick filter buton colors
    // if category has been selected, update the category color
    const urlParams = new URLSearchParams(window.location.search);

    if (urlParams.has('filter_type')) {
        const filterType = urlParams.get("filter_type");
        console.log("filter_type", filterType);
        associateQuickFilterButton = document.getElementById(`${filterType}-quick-filter-btn`);
        associateQuickFilterButton.classList.remove("btn-outline-primary");
        associateQuickFilterButton.classList.add("btn-primary");
    }

    // Highlight the category button if a category is selected
    const pathParts = window.location.pathname.split("/");
    const categoryNameFromPath = pathParts[pathParts.length - 1];  // Extract the category from the URL path


    if (categoryNameFromPath) {
        const categoryButton = document.getElementById(`category-${categoryNameFromPath.toLowerCase()}-btn`);
        if (categoryButton) {
            categoryButton.classList.remove("btn-outline-primary");
            categoryButton.classList.add("btn-primary");
        }
    }

    // when the AddProduct form opens, put the focus on the barcodeInput field
    var addProductModal = document.getElementById('addProductModal')
    addProductModal.addEventListener('shown.bs.modal', function () {
        var barcodeInput = addProductModal.querySelector('#barcode_product_add')
        barcodeInput.focus()

        // Event listener for the "Fetch Product" button
        var fetchProductBtn = addProductModal.querySelector('#fetchProductBtn');
        fetchProductBtn.addEventListener('click', function () {
            var barcode = document.getElementById('barcode_product_add').value

            // whenever the fetch button is clicked, first clear the form, only keep the barcode field
            var addProductForm = document.getElementById('addProductForm')
            addProductForm.reset()
            document.getElementById('barcode_product_add').value = barcode

            if (!barcode) {
                var fetchSuccessMessageElement = document.getElementById('fetch_call_response_message_product_add')
                fetchSuccessMessageElement.className = 'text-center text-danger mb-3'
                fetchSuccessMessageElement.innerText = 'Please enter the barcode first'
                fetchSuccessMessageElement.style.display = 'block'
            } else {
                fetchProductDetailsFromOpenFood(barcode)
            }
        })

        // Use the targetModalId to select the modal form
        var calculateSPButton = addProductModal.querySelector('#calculateSellingPricebtn')
        var calculatePMButton = addProductModal.querySelector('#calculateProfitMarginbtn')


        calculateSPButton.addEventListener('click', function () {
            var costPriceInput = addProductModal.querySelector('#cost_price').value;
            var profitMarginInput = addProductModal.querySelector('#profit_margin').value;

            var costPrice = parseFloat(costPriceInput);
            var profitMargin = parseFloat(profitMarginInput);

            if (!isNaN(costPrice) && !isNaN(profitMargin)) {
                var sellingPrice = costPrice * (1 + profitMargin / 100);
                addProductModal.querySelector('#price').value = Math.round(sellingPrice * 100) / 100;
            } else {
                alert('Please enter valid values for Cost Price and Profilt Margin');
            }
            console.log(costPrice);
            console.log(profitMargin);
            console.log(sellingPrice);

        })

        calculatePMButton.addEventListener('click', function () {
            var costPriceInput = addProductModal.querySelector('#cost_price').value;
            var sellingPriceInput = addProductModal.querySelector('#price').value;

            var costPrice = parseFloat(costPriceInput);
            var sellingPrice = parseFloat(sellingPriceInput);

            if (!isNaN(costPrice) && !isNaN(sellingPrice) && (costPrice > 0) && (sellingPrice > costPrice)) {
                var profitMargin = (sellingPrice / costPrice - 1) * 100;
                addProductModal.querySelector('#profit_margin').value = Math.round(profitMargin * 100) / 100;
            } else {
                alert('Please enter valid values for Cost Price and Selling Price');
            }


            console.log("Cost Price: ", costPrice);
            console.log("Profit Margin: ", profitMargin);
            console.log("Selling Price: ", sellingPrice);

        })

        // When the Enter key is pressed in the barcode input field, trigger the click event of the Fetch Product button
        barcodeInput.addEventListener('keypress', function (event) {
            if (event.key === 'Enter') {
                event.preventDefault() // Prevent the default Enter key behavior
                fetchProductBtn.click()
                barcodeInput.blur()
            }
        })

        // prevent form submission when enter is pressed in form input fields
        document.body.addEventListener('keypress', function (event) {
            console.log(`Key pressed in: ${event.target.tagName}`); // Debug line to see the target element type
            if (event.key === 'Enter' && event.target.id !== 'barcode_product_add' && event.target.tagName !== 'TEXTAREA') {
                console.log('Enter was pressed on non-barcode, non-textarea field');
                event.preventDefault();
            }
        });

        // populate the subcategories according to the category selected in product add form
        var categorySelect = addProductModal.querySelector('#select-category')
        var subCategorySelect = addProductModal.querySelector('#sub-category-select')

        handleCategoryChange(categorySelect, subCategorySelect)

        addProductModal.querySelector('#addProductFormResetBtn').addEventListener('click', function () {
            var addProductForm = addProductModal.querySelector('#addProductForm')
            addProductForm.reset()

            var fetchSuccessMessageElement = addProductModal.querySelector('#fetch_call_response_message_product_add')
            fetchSuccessMessageElement.className = ''
            fetchSuccessMessageElement.innerText = ''
            fetchSuccessMessageElement.style.display = 'none'
        })

        addProductModal.querySelector("#productImage_add").addEventListener("change", function () {
            checkFileSize(this);
        });

    })

    // select all the button whose id starts with product-update-button
    const productUpdateButtons = document.querySelectorAll('[id^="product-update-button"]')
    // when any product-update button is clicked, retreieve the product-update-modal form associated with it and add change event listener to the corresponding select-category element
    productUpdateButtons.forEach(function (button) {
        button.addEventListener('click', function () {
            // Get the value of data-bs-target attribute
            var targetModalId = this.getAttribute('data-bs-target');

            // Use the targetModalId to select the modal form
            var modal = document.querySelector(targetModalId);

            // populate the subcategories according to the category selected in product update form
            var categorySelectProductUpdate = modal.querySelector('#select-category-update');
            var subCategorySelectProductUpdate = modal.querySelector('#sub-category-select-update');
            handleCategoryChange(categorySelectProductUpdate, subCategorySelectProductUpdate);

            // handle the calculateSP button click
            var calculateSPUpdateButton = modal.querySelector('#calculateSellingPriceUpdatebtn');
            var calculatePMUpdateButton = modal.querySelector('#calculateProfitMarginUpdatebtn');
            calculateSPUpdateButton.addEventListener('click', function () {
                // Use the targetModalId to select the modal form
                var costPriceUpdate = modal.querySelector('#cost_price_product_update').value;
                var profitMarginUpdate = modal.querySelector('#profit_margin_product_update').value;

                console.log("costPriceUpdate: ", costPriceUpdate);
                console.log("profitMarginUpdate: ", profitMarginUpdate)
                if (!isNaN(costPriceUpdate) && !isNaN(profitMarginUpdate)) {
                    const sellingPriceUpdate = costPriceUpdate * (1 + profitMarginUpdate / 100);
                    modal.querySelector('#price_product_update').value = Math.round(sellingPriceUpdate * 100) / 100;

                } else {
                    alert('Please enter valid values for Cost Price and Profit Margin');
                }

            });

            calculatePMUpdateButton.addEventListener('click', function () {
                // Use the targetModalId to select the modal form
                var costPriceUpdate = modal.querySelector('#cost_price_product_update').value;
                var sellingPriceUpdate = modal.querySelector('#price_product_update').value;

                if (!isNaN(costPriceUpdate) && !isNaN(sellingPriceUpdate) && sellingPriceUpdate > costPriceUpdate && (costPriceUpdate > 0)) {
                    const profitMarginUpdate = (sellingPriceUpdate - costPriceUpdate) / costPriceUpdate * 100;
                    modal.querySelector('#profit_margin_product_update').value = Math.round(profitMarginUpdate * 100) / 100;

                } else {
                    alert('Please enter valid values for Cost Price and Selling Price');
                }

            });

            modal.querySelector("#productImage_update").addEventListener("change", function () {
                checkFileSize(this);
            });

        })
    })



    // when the AddProductStock form opens, put the focus on the barcodeInput field
    var addProductStockModal = document.getElementById('addProductStockModal')
    addProductStockModal.addEventListener('shown.bs.modal', function () {
        var barcodeInput = addProductStockModal.querySelector('#barcodeProductStockAdd');
        var addProductStockBtn = addProductStockModal.querySelector('#addProductStockBtn');
        barcodeInput.focus()
        addProductStockBtn.style = 'none';
        const addProductStockModalResetAll = () => {
            barcodeInput.value = '';
            barcodeInput.focus();
            productNameSpanInAddStock.innerText = '';
            productStockSpanInAddStock.innerText = '';
            addProductStockBtn.style = 'none';
        }

        // Listen for Enter key press in the barcode input
        barcodeInput.addEventListener('keypress', async function (event) {
            if (event.key === 'Enter') {
                event.preventDefault(); // Prevent the default Enter key behavior
                const barcode = event.target.value.trim();

                if (barcode) {
                    // Call the backend to fetch product details
                    const productData = await fetchProductByBarcode(barcode);
                    if (productData) {
                        // Update the product name and price spans
                        productNameSpanInAddStock.innerText = productData.name || 'N/A';
                        productStockSpanInAddStock.innerText = productData.stock_quantity;
                        addProductStockBtn.style = 'block';

                    } else {
                        console.error('Product not found. Please try again.');
                        addProductStockModalResetAll();

                    }
                }
            }
        });

        addProductStockBtn.addEventListener('onClick', async function () {

        });
    })


    const linkProductsModal = document.getElementById('linkProductsModal');
    linkProductsModal.addEventListener('shown.bs.modal', function () {
        // logic related to link products modal form

        const fetchProductsBtn = linkProductsModal.querySelector('#fetchProductsBtn');
        const linkBtn = linkProductsModal.querySelector('#linkBtn');

        fetchProductsBtn.addEventListener('click', function () {
            const productBarcode = linkProductsModal.querySelector('#productBarcode').value;
            const boxProductBarcode = linkProductsModal.querySelector('#boxProductBarcode').value;

            // Set URL for fetching product details
            const fetchProductUrl = urlConfig.fetchProductByBarcode + "?barcode=" + productBarcode;
            const fetchBoxProductUrl = urlConfig.fetchProductByBarcode + "?barcode=" + boxProductBarcode;

            if (productBarcode && boxProductBarcode) {
                // Fetch product details using AJAX
                Promise.all([
                    fetch(fetchProductUrl).then(response => response.json()),
                    fetch(fetchBoxProductUrl).then(response => response.json())
                ])
                    .then(([productData, boxProductData]) => {
                        // Update modal content with fetched product details
                        linkProductsModal.querySelector('#productNameSpan').innerText = productData.name;
                        linkProductsModal.querySelector('#boxProductNameSpan').innerText = boxProductData.name;

                        linkProductsModal.querySelector('#productPriceSpan').innerText = productData.price;
                        linkProductsModal.querySelector('#boxProductPriceSpan').innerText = boxProductData.price;

                        // Freeze the barcode fields
                        linkProductsModal.querySelector('#productBarcode').readOnly = true;
                        linkProductsModal.querySelector('#boxProductBarcode').readOnly = true;

                        // Enable the link and reset button
                        linkBtn.style.display = 'block';
                        resetLinkFormBtn.style.display = 'block';

                        //Disable the fetch button
                        fetchProductsBtn.style.display = 'none';
                    })
                    .catch(error => {
                        console.error('Error fetching product details:', error);
                        alert('Error fetching product details');
                    });
            }
            else {
                alert('Please enter both barcodes before pressing the fetch button')
            }
        });

        resetLinkFormBtn.addEventListener('click', function () {
            linkProductsForm.reset();

            // Unfreeze the barcode fields
            //document.getElementById('productBarcode').disabled = false;
            //document.getElementById('boxProductBarcode').disabled = false;

            // Disable the link and reset button
            linkBtn.style.display = 'none';
            resetLinkFormBtn.style.display = 'none';

            //Enable the fetch button
            fetchProductsBtn.style.display = 'block';

            // Update modal content with fetched product details
            linkProductsModal.querySelector('#productNameSpan').innerText = null;
            linkProductsModal.querySelector('#boxProductNameSpan').innerText = null;

            linkProductsModal.querySelector('#productPriceSpan').innerText = null;
            linkProductsModal.querySelector('#productBoxPriceSpan').innerText = null;
        });

    })


    // Logic related to batch update modal form
    const batchUpdateModal = document.getElementById('batchUpdateModal');
    // Add event listener when the modal is shown
    batchUpdateModal.addEventListener('shown.bs.modal', function () {

        const barcodeInput = batchUpdateModal.querySelector('#batchUpdateProductBarcode');
        const batchProductUpdateNameSpan = batchUpdateModal.querySelector('#batchProductUpdateNameSpan');
        const batchProductUpdatePriceSpan = batchUpdateModal.querySelector('#batchProductUpdatePriceSpan');
        const productBarcodesTextarea = batchUpdateModal.querySelector('#productBarcodesTextarea');
        const addBarcodeButton = batchUpdateModal.querySelector('#addBarcodeBtn');
        const cancelBarcodeButton = batchUpdateModal.querySelector('#cancelBarcodeBtn');
        barcodeInput.focus();

        let productBarcodes = [];

        // Hide the Add button initially
        addBarcodeButton.style.display = 'none';
        cancelBarcodeButton.style.display = 'none';

        // Listen for Enter key press in the barcode input
        barcodeInput.addEventListener('keypress', async function (event) {
            if (event.key === 'Enter') {
                event.preventDefault(); // Prevent the default Enter key behavior
                const barcode = event.target.value.trim();

                if (barcode) {
                    // Call the backend to fetch product details
                    const productData = await fetchProductByBarcode(barcode);
                    if (productData) {
                        // Update the product name and price spans
                        batchProductUpdateNameSpan.innerText = productData.name || 'N/A';
                        batchProductUpdatePriceSpan.innerText = productData.price;

                        // Show the Add button
                        addBarcodeButton.style.display = 'block';
                        cancelBarcodeButton.style.display = 'block';
                        barcodeInput.blur();

                    } else {
                        console.error('Product not found. Please try again.');
                        barcodeInput.value = '';
                        barcodeInput.focus();
                    }
                }
            }
        });

        // Listen for click on the Add button
        addBarcodeButton.addEventListener('click', function () {
            const productName = batchProductUpdateNameSpan.innerText;
            const productPrice = batchProductUpdatePriceSpan.innerText;

            if (productName && productPrice) {
                // Get the barcode from the fetched product details
                const barcode = barcodeInput.value.trim();

                // Add the barcode to the productBarcodes list if not already there
                if (productBarcodes.indexOf(barcode) === -1) {
                    productBarcodes.push(barcode);

                    // Update the uneditable textarea with the list of barcodes
                    productBarcodesTextarea.value = productBarcodes.join(', ');

                    // Clear barcode input field and product details
                    barcodeInput.value = '';
                    batchProductUpdateNameSpan.innerText = '';
                    batchProductUpdatePriceSpan.innerText = '';

                } else {
                    alert('This product is already added.');
                    barcodeInput.value = '';
                }
            } else {
                alert('No product details found. Please scan a valid product barcode.');
                barcodeInput.value = '';
            }
            // Hide the Add button again
            barcodeInput.focus();
            addBarcodeButton.style.display = 'none';
            cancelBarcodeButton.style.display = 'none';
        });

        // Listen for click on the Add button
        cancelBarcodeButton.addEventListener('click', function () {

            // Clear barcode input field and product details
            barcodeInput.value = '';
            barcodeInput.focus();
            batchProductUpdateNameSpan.innerText = '';
            batchProductUpdatePriceSpan.innerText = '';

            // Hide the Add button again
            addBarcodeButton.style.display = 'none';
            cancelBarcodeButton.style.display = 'none';
        });

        // Reset the modal when it is closed
        batchUpdateModal.addEventListener('hidden.bs.modal', function () {
            batchProductUpdateNameSpan.innerText = '';
            batchProductUpdatePriceSpan.innerText = '';
            barcodeInput.value = '';
            productBarcodesTextarea.value = '';
            productBarcodes = [];
            addBarcodeButton.style.display = 'none';
        });
    });

    // Logic related to price update modal form
    const priceUpdateModal = document.getElementById('priceUpdateModal');
    // Add event listener when the modal is shown
    priceUpdateModal.addEventListener('shown.bs.modal', function () {

        const barcodeInput = priceUpdateModal.querySelector('#priceUpdateProductBarcode');
        const priceUpdateNameSpan = priceUpdateModal.querySelector('#priceUpdateNameSpan');
        const priceUpdatePriceSpan = priceUpdateModal.querySelector('#priceUpdatePriceSpan');
        const priceUpdateNetContentSpan = priceUpdateModal.querySelector('#priceUpdateNetContentSpan');
        const priceUpdateBasePrice = priceUpdateModal.querySelector('#priceUpdateBasePrice');
        const priceUpdateProfitMargin = priceUpdateModal.querySelector('#priceUpdateProfitMargin');
        const priceUpdateNewPrice = priceUpdateModal.querySelector('#priceUpdateNewPrice');
        const cancelBarcodeButton = priceUpdateModal.querySelector('#cancelBarcodeBtn');
        const priceUpdateCalculateProfitMarginbtn = priceUpdateModal.querySelector('#priceUpdateCalculateProfitMarginbtn');
        const priceUpdateCalculateNewPricebtn = priceUpdateModal.querySelector('#priceUpdateCalculateNewPricebtn')

        const priceUpdateModalResetAll = () => {
            barcodeInput.value = '';
            barcodeInput.focus();
            priceUpdateNameSpan.innerText = '';
            priceUpdatePriceSpan.innerText = '';
            priceUpdateNetContentSpan.innerText = '';
            priceUpdateBasePrice.value = '';
            priceUpdateProfitMargin.value = '';
            priceUpdateNewPrice.value = '';
            cancelBarcodeButton.style.display = 'none';
        }
        barcodeInput.focus();


        // Hide the Add button initially
        cancelBarcodeButton.style.display = 'none';

        // Listen for Enter key press in the barcode input
        barcodeInput.addEventListener('keypress', async function (event) {
            if (event.key === 'Enter') {
                event.preventDefault(); // Prevent the default Enter key behavior
                const barcode = event.target.value.trim();

                if (barcode) {
                    // Call the backend to fetch product details
                    const productData = await fetchProductByBarcode(barcode);
                    if (productData) {
                        // Update the product name and price spans
                        priceUpdateNameSpan.innerText = productData.name || 'N/A';
                        priceUpdatePriceSpan.innerText = productData.price;
                        priceUpdateNetContentSpan.innerText = productData.net_contents;
                        priceUpdateBasePrice.value = productData.price;

                        // Show the Add button
                        cancelBarcodeButton.style.display = 'block';
                        barcodeInput.blur();

                    } else {
                        console.error('Product not found. Please try again.');
                        priceUpdateModalResetAll();

                    }
                }
            }
        });


        priceUpdateCalculateNewPricebtn.addEventListener('click', async function (event) {
            // Calculate new price and round it off to 2 decimal points
            let newPrice = priceUpdateBasePrice.value * (1 + priceUpdateProfitMargin.value / 100);
            priceUpdateNewPrice.value = parseFloat(newPrice.toFixed(2));
            event.stopPropagation();
        });

        priceUpdateCalculateProfitMarginbtn.addEventListener('click', async function (event) {
            // Calculate profit margin and round it off to 2 decimal points
            let profitMargin = (priceUpdateNewPrice.value / priceUpdateBasePrice.value - 1) * 100;
            priceUpdateProfitMargin.value = parseFloat(profitMargin.toFixed(2));
            event.stopPropagation();
        });



        // Listen for click on the Add button
        cancelBarcodeButton.addEventListener('click', function () {

            // Clear barcode input field and product details
            priceUpdateModalResetAll();
        });

        // Reset the modal when it is closed
        priceUpdateModal.addEventListener('hidden.bs.modal', function () {
            priceUpdateModalResetAll();

        });
    });

    // logic related to product approval
    const productApproveButtons = document.querySelectorAll('[id^="product-approve-button"]')
    productApproveButtons.forEach(function (button) {
        button.addEventListener('click', async function () {

            let productId = this.getAttribute("data-product-id");
            const currentUrl = window.location.href;

            response = await approveProduct(productId)
            if (response.success) {
                button.disabled = true;
                window.location.href = currentUrl;
            }
            else {
                alert(`Approval failed: ${result.message}`)
            }

        })
    })

    // logic related to export product
    const exportProductButton = document.getElementById('export-products-btn')
    exportProductButton.addEventListener('click', exportProductsExcel)

    // logic related to upload epos file
    const syncDataWithEposModal = document.getElementById('syncDataWithEposModal');
    syncDataWithEposModal.addEventListener('shown.bs.modal', function () {
        const eposFileInput = syncDataWithEposModal.querySelector('#eposFileInput');
        const uploadEposFileBtn = syncDataWithEposModal.querySelector('#uploadEposFileBtn');
        eposFileInput.value = '';
        uploadEposFileBtn.disabled = true;
        eposFileInput.addEventListener('change', function () {
            if (eposFileInput.files.length > 0) {
                uploadEposFileBtn.disabled = false;
            }   
            else {
                uploadEposFileBtn.disabled = true;
            }   
        });
    });
        

    //logic related to marketing opted users fetch
    const marketingOptedUsersButton = document.getElementById('marketing-opted-users-btn')
    marketingOptedUsersButton.addEventListener('click', exportMarketingOptedUsers)

    const addCategoryModal = document.getElementById('addCategoryModal');
    addCategoryModal.addEventListener('shown.bs.modal', function () {
        addCategoryModal.querySelector("#categoryImage_add").addEventListener("change", function () {
            checkFileSize(this);
        });
    });

    const eposDataSyncform = document.getElementById("syncDataWithEposForm");
    const progress = document.getElementById("eposDataSyncProgress");

    eposDataSyncform.addEventListener("submit", function () {
        // Show the progress bar
        progress.classList.remove("d-none");

        // Disable the submit button to prevent multiple clicks
        const submitBtn = eposDataSyncform.querySelector("button[type='submit']");
        submitBtn.disabled = true;
        submitBtn.textContent = "Syncing...";

        // Optional: Prevent closing modal while syncing
        const modalCloseBtn = document.querySelector("#syncDataWithEposModal .btn-close");
        modalCloseBtn.style.display = "none";
    });


}
document.addEventListener('DOMContentLoaded', initialize());