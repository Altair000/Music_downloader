function toggleHistory() {
    const historyDiv = document.getElementById('history');
    if (historyDiv.classList.contains('show')) {
        historyDiv.classList.remove('show');
    } else {
        fetch('/history')
            .then(response => response.json())
            .then(data => {
                historyDiv.innerHTML = '';
                if (data.length === 0) {
                    toastr.info('No hay descargas en el historial.');
                    return;
                }
                data.forEach(item => {
                    const p = document.createElement('p');
                    p.className = 'dropdown-item';
                    p.textContent = `${item[0]} (${item[1]} kbps) - ${item[2]}`;
                    historyDiv.appendChild(p);
                });
                historyDiv.classList.add('show');
            })
            .catch(error => {
                toastr.error('Error al cargar el historial: ' + error);
            });
    }
}