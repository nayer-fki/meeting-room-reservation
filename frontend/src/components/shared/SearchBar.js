// frontend/src/components/shared/SearchBar.js
import React from 'react';
import './SearchBar.css';

const SearchBar = ({ placeholder, value, onChange }) => {
  const handleClear = () => {
    onChange({ target: { value: '' } }); // Simulate an onChange event to clear the input
  };

  return (
    <div className="search-bar-wrapper">
      <span className="search-icon">🔍</span>
      <input
        type="text"
        placeholder={placeholder}
        value={value}
        onChange={onChange}
        className="search-bar"
        aria-label="Rechercher des salles par nom"
      />
      {value && (
        <button
          type="button"
          onClick={handleClear}
          className="clear-button"
          aria-label="Effacer la recherche"
        >
          ✕
        </button>
      )}
    </div>
  );
};

export default SearchBar;